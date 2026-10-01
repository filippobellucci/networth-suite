"""
Counterparty -> category rules (see models.MerchantRule).

Everything here works on the *normalized* counterparty name: a bank can spell
the same merchant differently from one message to the next -- Revolut sends
"Unicoop Firenze-Ponsacco" while a card payment is pending and "Unicoop
Firenze-ponsacco" once it's booked -- and the two must be one merchant, not
two to map separately.
"""
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def normalize(name: Optional[str]) -> str:
    """Case-insensitive, whitespace-collapsed. "" for nothing usable."""
    return " ".join(str(name or "").split()).casefold()


class RuleBook:
    """
    Every rule, loaded once, answering "which rule decides this counterparty?"

    An EXACT rule for the name wins; otherwise the longest CONTAINS rule whose
    pattern is part of the name, so a more specific "coop assicurazioni"
    beats "coop" whatever order they were created in. An *ignored* rule
    decides too -- it's what stops a broader CONTAINS rule from categorizing
    a counterparty you deliberately left out.
    """

    def __init__(self, db: Session):
        rules = db.query(models.MerchantRule).all()
        self._exact = {r.pattern: r for r in rules if r.match_type == models.MerchantMatchType.EXACT}
        self._contains = sorted(
            (r for r in rules if r.match_type == models.MerchantMatchType.CONTAINS),
            key=lambda r: (-len(r.pattern), r.pattern),
        )

    def match(self, key: str) -> Optional[models.MerchantRule]:
        if not key:
            return None
        rule = self._exact.get(key)
        if rule is not None:
            return rule
        for rule in self._contains:
            if rule.pattern in key:
                return rule
        return None

    def category_for(self, key: str) -> Optional[str]:
        rule = self.match(key)
        if rule is None or rule.ignored:
            return None
        return rule.category_id


def _decided_by(db: Session, rule: models.MerchantRule):
    """The transactions this rule is the deciding one for -- not those an
    EXACT rule, or a longer CONTAINS rule, decides instead. Transfer legs are
    left out: they can't be edited, and aren't spending or income anyway."""
    book = RuleBook(db)
    q = db.query(models.CashTransaction).filter(
        models.CashTransaction.counterparty_key.isnot(None),
        models.CashTransaction.transfer_id.is_(None),
    )
    if rule.match_type == models.MerchantMatchType.EXACT:
        q = q.filter(models.CashTransaction.counterparty_key == rule.pattern)
    return [t for t in q.all() if book.match(t.counterparty_key) is rule]


def apply_to_uncategorized(db: Session, rule: models.MerchantRule) -> int:
    """Gives this rule's category to its transactions that have none yet.
    One that already has a category -- set by hand, or by a bank's MCC -- is
    never touched. Returns how many changed; the caller commits."""
    if rule.ignored or not rule.category_id:
        return 0
    changed = 0
    for t in _decided_by(db, rule):
        if t.category_id is None:
            t.category_id = rule.category_id
            changed += 1
    return changed


def move_from_category(db: Session, rule: models.MerchantRule, previous_category_id: Optional[str]) -> int:
    """Moves this rule's transactions still in `previous_category_id` (the
    category the rule had before) to its current one."""
    if not previous_category_id or rule.ignored or not rule.category_id:
        return 0
    changed = 0
    for t in _decided_by(db, rule):
        if t.category_id == previous_category_id:
            t.category_id = rule.category_id
            changed += 1
    return changed

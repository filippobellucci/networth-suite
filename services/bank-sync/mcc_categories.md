# Merchant Category Code (MCC) reference

Standardized codes (ISO 18245) that most banks/card networks attach to card transactions, used by
`mcc_categories.yaml` to auto-assign a category. The official list has roughly 700 codes; this
covers the ranges a personal account actually sees. Codes not listed here can still be used --
look them up and add them to `mcc_categories.yaml` yourself, the mapping isn't limited to this table.

## Food & dining

| MCC | Meaning |
|---|---|
| 5411 | Grocery Stores, Supermarkets |
| 5412 | Fruit and Vegetable Markets |
| 5422 | Freezer and Locker Meat Provisioners |
| 5441 | Candy, Nut, Confectionery Stores |
| 5451 | Dairy Products Stores |
| 5462 | Bakeries |
| 5499 | Misc. Food Stores, Convenience Stores, Markets |
| 5811 | Caterers |
| 5812 | Eating Places, Restaurants |
| 5813 | Drinking Places (Bars, Taverns, Pubs) |
| 5814 | Fast Food Restaurants |

## Transport

| MCC | Meaning |
|---|---|
| 4111 | Local/Suburban Commuter Transport (trains, ferries) |
| 4112 | Passenger Railways |
| 4119 | Ambulance Services |
| 4121 | Taxicabs, Limousines |
| 4131 | Bus Lines |
| 4214 | Motor Freight Carriers, Trucking |
| 4411 | Cruise Lines |
| 4457 | Boat Rentals and Leasing |
| 4468 | Marinas, Marine Service, Supplies |
| 4784 | Toll and Bridge Fees |
| 4789 | Transportation Services (not elsewhere classified) |
| 5511 | Car and Truck Dealers (New/Used) |
| 5541 | Service Stations (Fuel) |
| 5542 | Automated Fuel Dispensers |
| 5571 | Motorcycle Shops, Dealers |
| 7512 | Car Rental Agencies |
| 7523 | Parking Lots, Garages |
| 7531 | Auto Body Repair Shops |
| 7534 | Tire Retreading and Repair |
| 7538 | Auto Service Shops |
| 7542 | Car Washes |

## Travel & lodging

| MCC | Meaning |
|---|---|
| 3000–3299 | Airlines (each carrier has its own code in this range) |
| 3300–3499 | Car Rental Agencies (each company has its own code) |
| 3500–3999 | Hotels, Motels, Resorts (each chain has its own code) |
| 4511 | Airlines, Air Carriers (generic) |
| 4722 | Travel Agencies, Tour Operators |
| 4723 | TUI Travel — Germany |
| 7011 | Hotels, Motels, Resorts (generic) |
| 7012 | Timeshares |

## Bills & utilities

| MCC | Meaning |
|---|---|
| 4812 | Telecom Equipment |
| 4813 | Key-entry Telecom Merchant |
| 4814 | Telecommunication Services (phone/internet bills) |
| 4816 | Computer Network/Information Services |
| 4821 | Telegraph Services |
| 4899 | Cable, Satellite, Other Pay TV/Radio |
| 4900 | Utilities — Electric, Gas, Water, Sanitary |

## Health

| MCC | Meaning |
|---|---|
| 5912 | Drug Stores, Pharmacies |
| 5975 | Hearing Aids — Sales, Service |
| 5976 | Orthopedic Goods, Prosthetic Devices |
| 8011 | Doctors, Physicians (not elsewhere classified) |
| 8021 | Dentists, Orthodontists |
| 8031 | Osteopaths |
| 8041 | Chiropractors |
| 8042 | Optometrists, Ophthalmologists |
| 8043 | Opticians, Eyeglasses |
| 8049 | Podiatrists, Chiropodists |
| 8050 | Nursing/Personal Care Facilities |
| 8062 | Hospitals |
| 8071 | Medical/Dental Labs |
| 8099 | Medical Services (not elsewhere classified) |

## Shopping & apparel

| MCC | Meaning |
|---|---|
| 5611 | Men's/Boys' Clothing Stores |
| 5621 | Women's Ready-to-Wear Stores |
| 5631 | Women's Accessory Stores |
| 5641 | Children's/Infants' Wear Stores |
| 5651 | Family Clothing Stores |
| 5661 | Shoe Stores |
| 5691 | Men's/Women's Clothing Stores |
| 5699 | Miscellaneous Apparel/Accessory Shops |
| 5712 | Furniture, Home Furnishings |
| 5722 | Household Appliance Stores |
| 5731 | Electronics Sales |
| 5732 | Electronics Stores |
| 5733 | Music Stores — Instruments, Sheet Music |
| 5734 | Computer Software Stores |
| 5735 | Record Stores |
| 5811–5814 | see "Alimentari" above |
| 5912 | see "Salute" above |
| 5921 | Package Stores — Beer, Wine, Liquor |
| 5941 | Sporting Goods Stores |
| 5942 | Book Stores |
| 5943 | Stationery, Office Supplies |
| 5944 | Jewelry, Watches, Clocks, Silverware Stores |
| 5945 | Hobby, Toy, Game Shops |
| 5946 | Camera and Photographic Supply Stores |
| 5947 | Gift, Card, Novelty Shops |
| 5977 | Cosmetic Stores |
| 5992 | Florists |
| 5999 | Miscellaneous and Specialty Retail Stores |

## Entertainment & subscriptions

| MCC | Meaning |
|---|---|
| 5815 | Digital Goods — Media, Books, Movies, Music |
| 5816 | Digital Goods — Games |
| 5817 | Digital Goods — Applications (excl. games) |
| 5818 | Digital Goods — Large Multi-category Merchants |
| 7829 | Motion Picture and Video Tape Production/Distribution |
| 7832 | Motion Picture Theaters |
| 7841 | Video Tape Rental Stores |
| 7911 | Dance Halls, Studios, Schools |
| 7922 | Theatrical Producers, Ticket Agencies |
| 7929 | Bands, Orchestras, Entertainers (not elsewhere classified) |
| 7932 | Billiard/Pool Establishments |
| 7933 | Bowling Alleys |
| 7941 | Sports Clubs/Fields |
| 7991 | Tourist Attractions and Exhibits |
| 7992 | Golf Courses — Public |
| 7993 | Video Amusement Game Supplies |
| 7994 | Video Game Arcades |
| 7996 | Amusement Parks, Circuses |
| 7997 | Membership Clubs (Country, Athletic) |
| 7998 | Aquariums |
| 7999 | Recreation Services (not elsewhere classified) |

## Personal & professional services

| MCC | Meaning |
|---|---|
| 7211 | Laundry Services |
| 7216 | Dry Cleaners |
| 7221 | Photographic Studios |
| 7230 | Barber/Beauty Shops |
| 7251 | Shoe Repair, Shine, Hat Cleaning |
| 7261 | Funeral Services, Crematories |
| 7273 | Dating/Escort Services |
| 7276 | Tax Preparation Services |
| 7277 | Counseling Services — Debt, Marriage, Personal |
| 7278 | Buying/Shopping Services, Clubs |
| 7296 | Clothing Rental |
| 7297 | Massage Parlors |
| 7298 | Health and Beauty Spas |
| 7299 | Miscellaneous Personal Services |
| 8111 | Legal Services, Attorneys |
| 8211 | Elementary/Secondary Schools |
| 8220 | Colleges, Universities |
| 8241 | Correspondence Schools |
| 8244 | Business/Secretarial Schools |
| 8249 | Vocational/Trade Schools |
| 8299 | Schools, Educational Services (not elsewhere classified) |
| 8351 | Child Care Services |
| 8398 | Charitable/Social Service Organizations |
| 8641 | Civic, Social, Fraternal Associations |
| 8651 | Political Organizations |
| 8661 | Religious Organizations |
| 8675 | Automobile Associations |
| 8699 | Membership Organizations (not elsewhere classified) |
| 8931 | Accounting, Auditing, Bookkeeping |
| 8999 | Professional Services (not elsewhere classified) |

## Finance, insurance, government

| MCC | Meaning |
|---|---|
| 6011 | ATM Cash Withdrawals |
| 6012 | Financial Institutions — Merchandise/Services |
| 6051 | Non-FI, Money Orders |
| 6211 | Securities Brokers/Dealers |
| 6300 | Insurance Sales, Underwriting |
| 9211 | Court Costs, Alimony, Child Support |
| 9222 | Fines |
| 9311 | Tax Payments |
| 9399 | Government Services (not elsewhere classified) |
| 9402 | Postal Services — Government Only |
| 9405 | Government Services (US Federal/State/Local) |

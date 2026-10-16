"""
Shopcart — product catalog (single source of truth for names & prices).
========================================================================
Prices live ONLY here. The frontend never decides what an item costs;
every order total is recomputed on the server from this table so a
tampered browser can never change a price.

`stock` is seeded into SQLite on first run — after that the database
owns the counts (so purchases permanently reduce availability).
"""

CATALOG = {
    "earbuds-ipx8": dict(name="Wireless Earbuds, IPX8", price=89.00,
                         desc="Organic Cotton, fairtrade certified",
                         img="assets/img/earbuds-ipx8.png", rating=5, stock=24),
    "airpods-max":  dict(name="AirPods Max", price=559.00,
                         desc="A perfect balance of high-fidelity audio",
                         img="assets/img/headphone-red.png", rating=5, stock=12),
    "bose-bt":      dict(name="Bose BT Earphones", price=289.00,
                         desc="Table with air purifier, stained venner/black",
                         img="assets/img/headphone-black.png", rating=5, stock=18),
    "vivefox":      dict(name="VIVEFOX Headphones", price=39.00,
                         desc="Wired Stereo Headsets With Mic",
                         img="assets/img/headphone-redwired.png", rating=5, stock=30),
    "jbl-600":      dict(name="JBL TUNE 600BTNC", price=59.00,
                         desc="Premium Bone Conduction Open Ear Bluetooth",
                         img="assets/img/headphone-anc.png", rating=5, stock=15),
    "tagry":        dict(name="TAGRY Bluetooth", price=109.00,
                         desc="256, 8 core GPU, 8 GB",
                         img="assets/img/earbuds-tagry.png", rating=5, stock=3),   # low-stock demo
    "monster":      dict(name="Monster MNFLEX", price=89.75,
                         desc="Flex Active Noise Canceling Bluetooth",
                         img="assets/img/bone-conduction.png", rating=5, stock=0),  # out-of-stock demo
    "mpow":         dict(name="Mpow CH6", price=569.00,
                         desc="Kids Headphones",
                         img="assets/img/headphone-blue.png", rating=5, stock=9),
    "gaming":       dict(name="Gaming Headphone", price=239.00,
                         desc="Table with air purifier, stained venner/black",
                         img="assets/img/gaming-headset.png", rating=5, stock=14),
    "macbook":      dict(name='Macbook pro 13"', price=1099.00,
                         desc="256, 8 core GPU, 8 GB",
                         img="assets/img/laptop-pink.png", rating=5, stock=6),
    "homepod":      dict(name="HomePod mini", price=59.00,
                         desc="5 Colors Available",
                         img="assets/img/homepod-orange.png", rating=5, stock=21),
    "sleeve":       dict(name="Laptop sleeve MacBook", price=59.00,
                         desc="Organic Cotton, fairtrade certified",
                         img="assets/img/sleeve-yellow.png", rating=5, stock=27),
}

# Small colour map used on receipts / review screens (kept server-side so
# the order snapshot can record the colour the buyer picked).
COLOURS = {"airpods-max": "Pink", "mpow": "Blue", "tagry": "Iridescent"}

VALID_NETWORKS = {"visa", "mastercard", "verve", "amex", "discover", "unionpay"}

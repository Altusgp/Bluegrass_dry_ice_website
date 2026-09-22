"""Site content and catalog. Edit prices, hours, and copy here - the page and the
API both read from this file, so nothing goes out of sync."""

BUSINESS = {
    "name": "Bluegrass Dry Ice",
    "tagline": "Nicholasville · Lexington",
    "phone": "(859) 514-3114",
    "phone_href": "tel:+18595143114",
    "email": "orders@dryiceky.com",
    "street": "3004 Park Central Ave, Suite B",
    "city": "Nicholasville, KY 40356",
    "hours": ["Mon–Fri: 9:00 AM–5:00 PM", "Saturday: closed", "Sunday: closed"],
    "map_query": "3004+Park+Central+Ave,+Nicholasville,+KY+40356",
}

BAGS = [
    {"name": "10 lb bag", "lbs": 10, "price": 35, "per_lb": "$3.50/lb",
     "best_for": "Small coolers, short trips, fog effects"},
    {"name": "20 lb bag", "lbs": 20, "price": 60, "per_lb": "$3.00/lb",
     "best_for": "Shipping, medium coolers, day events"},
    {"name": "50 lb bag", "lbs": 50, "price": 140, "per_lb": "$2.80/lb",
     "best_for": "Freezer backup, large containers"},
    {"name": "100 lb bag", "lbs": 100, "price": 250, "per_lb": "$2.50/lb",
     "best_for": "Large shipments and high-volume cooling"},
]

CONTAINERS = [
    {"label": "I'm bringing my own cooler", "price": 0},
    {"label": "Small / standard foam container", "price": 10},
    {"label": "Medium foam container", "price": 18},
    {"label": "Large foam container", "price": 25},
]

# image = file under static/images/. A missing file falls back to the gradient.
USE_CASES = [
    {"title": "Food & Beverage", "image": "DIKY_food_and_beverage_image.png", "fallback": "#f3d9b8,#c98f4e",
     "text": "Keep food frozen, support food processing, and handle specialty beverage applications."},
    {"title": "Shipping & Transport", "image": "DIKY_shipping_and_transport_image.jpg", "fallback": "#cfe0f2,#7f9fc4",
     "text": "Maintain colder conditions for temperature-sensitive products while they are packed or in transit."},
    {"title": "Emergency Cooling", "image": "DIKY_Emergency_cooling_image.png", "fallback": "#f6e0c5,#d99a5c",
     "text": "Get temporary cold support when the power goes out or refrigeration equipment stops working."},
    {"title": "Camping, Hunting & Outdoors", "image": "DIKY_Camping_Image.png", "fallback": "#d7e7cf,#7c9d72",
     "text": "Keep coolers colder for longer on camping, hunting, fishing, boating, and extended outdoor trips."},
    {"title": "Events & Special Effects", "image": "DIKY_Events_specialfx_image.jpg", "fallback": "#e0d4f2,#8d73bd",
     "text": "Create dramatic low-lying fog and memorable visual effects for parties, displays, and productions."},
    {"title": "Science, Labs & Education", "image": "DIKY_Science_Lab_Image.jpeg", "fallback": "#cfe9ec,#6ea6ad",
     "text": "Useful for demonstrations, research workflows, sample cooling, and hands-on science applications."},
    {"title": "Industrial & Maintenance", "image": "DIKY_industrial_maintenance_image.png", "fallback": "#dcdfe4,#8a919c",
     "text": "Support specialty cleaning, manufacturing, fitting, cooling, and maintenance processes."},
    {"title": "Agriculture & Specialty Uses", "image": "DIKY_Agriculture_Image.png", "fallback": "#dcebc8,#8aa85f",
     "text": "Flexible pelletized dry ice for agricultural, plant-handling, production, and specialty commercial needs."},
]

SAFETY_RULES = [
    {"icon": "🧤", "title": "Use insulated gloves or tongs",
     "text": "Direct skin contact can cause severe frostbite in seconds. Never handle pellets with bare hands."},
    {"icon": "🚗", "title": "Ventilate during transport",
     "text": "Keep fresh air moving in enclosed vehicles and never leave dry ice in an occupied sealed space."},
    {"icon": "⚠️", "title": "Never use an airtight container",
     "text": "Carbon dioxide gas must be able to escape as the dry ice sublimates, or pressure can build dangerously."},
    {"icon": "🚫", "title": "Never touch, taste, or ingest",
     "text": "Keep dry ice away from children and pets, and use it only for its intended purpose."},
]

WONT_DO = [
    "We do not ship dry ice from this location.",
    "We do not place dry ice in airtight containers.",
    "We do not accept returns on unused dry ice.",
    "We do not recommend transporting it in unventilated passenger compartments.",
]

GUIDES = [
    {"icon": "📦", "title": "Shipping frozen food with dry ice",
     "text": "Packing sequence, ventilation, timing, and how much to start with."},
    {"icon": "❄️", "title": "Keeping a freezer cold during an outage",
     "text": "Where to place dry ice and how to minimize cold loss safely."},
    {"icon": "🎃", "title": "Making fog for Halloween or a party",
     "text": "Create dense low-lying fog and manage water temperature safely."},
    {"icon": "🏕️", "title": "Camping & hunting coolers",
     "text": "Keep frozen items frozen longer without turning the cooler into an airtight box."},
    {"icon": "⏱️", "title": "How long does dry ice last?",
     "text": "Understand sublimation and the factors that change how quickly dry ice disappears."},
    {"icon": "🧊", "title": "Pellets vs. blocks",
     "text": "Why pellets are convenient for flexible packing, fog effects, and portioning."},
]

FAQS = [
    {"q": "How fast does dry ice sublimate?",
     "a": "A common planning range is roughly 5–10 lb per 24 hours in a well-insulated cooler. Actual loss varies "
          "with temperature, insulation, air space, and how often the container is opened."},
    {"q": "What size are the pellets?",
     "a": "We stock standard pelletized dry ice, which is easy to portion, fills voids around products, and works "
          "well for both cooling and fog effects."},
    {"q": "Do you sell blocks?",
     "a": "This location is built around dry ice pellets. If you need blocks for a specific application, call or "
          "text us and we'll tell you what we can do."},
    {"q": "Can I get dry ice the same day?",
     "a": "Yes, when inventory is available. Same-day pickup is available from 9:00 AM to 5:00 PM, Monday "
          "through Friday."},
    {"q": "Can I return unused dry ice?",
     "a": "No. Dry ice sublimates continuously, so all dry ice sales are final."},
    {"q": "Can I store dry ice in my freezer?",
     "a": "Dry ice is far colder than a household freezer and can trip the thermostat or damage the appliance. "
          "Store it in a ventilated insulated container instead."},
]

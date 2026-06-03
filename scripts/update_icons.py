import os
import sys
import re

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from app.models.amenity import Amenity

db = SessionLocal()

VALID_ICONS = [
    'wifi', 'tv', 'phone', 'snowflake', 'thermometer', 'wine', 'bed-double', 'cloud',
    'coffee', 'car', 'sun', 'moon', 'star', 'music', 'briefcase', 'shield', 'key',
    'lock', 'unlock', 'bell', 'camera', 'video', 'mic', 'headphones', 'monitor',
    'laptop', 'tablet', 'smartphone', 'watch', 'battery-full', 'battery-empty',
    'battery-charging', 'power', 'zap', 'activity', 'heart', 'droplet', 'wind',
    'flame', 'umbrella', 'map-pin', 'navigation', 'compass', 'globe', 'anchor',
    'plane', 'train', 'truck', 'bike', 'bus', 'car-taxi-front', 'palmtree',
    'waves', 'shirt', 'sparkles', 'droplets', 'key-round', 'sunrise', 'mountain', 
    'door-open', 'trees', 'clock', 'bath'
]

def map_icon(name, current_icon):
    n = name.lower()
    
    # Priority 1: Exact or very specific matches
    if any(x in n for x in ['wifi', 'wi-fi', 'internet']): return 'wifi'
    if any(x in n for x in ['tv', 'televis']): return 'tv'
    if any(x in n for x in ['jacuzzi', 'piscina', 'pool']): return 'waves'
    if any(x in n for x in ['bañera', 'tina', 'bath']): return 'bath'
    if any(x in n for x in ['ducha', 'shower']): return 'droplets'
    if any(x in n for x in ['aire acondicionado', 'climatizador', 'snowflake']): return 'snowflake'
    # Use regex for 'ac' to avoid matching 'estacionamiento'
    if re.search(r'\bac\b', n): return 'snowflake'
    
    if any(x in n for x in ['parqueo', 'estacionamiento', 'parking']): return 'car'
    if any(x in n for x in ['cafe', 'coffee', 'cafetera']): return 'coffee'
    if any(x in n for x in ['bata', 'ropa', 'vestir']): return 'shirt'
    if any(x in n for x in ['premium', 'lujo', 'vip', 'sparkle']): return 'sparkles'
    if any(x in n for x in ['cerradura', 'llave']): return 'key-round'
    if any(x in n for x in ['mar', 'playa', 'ocean']): return 'sunrise'
    if any(x in n for x in ['montaña', 'volcan']): return 'mountain'
    if any(x in n for x in ['balcón', 'balcon', 'patio']): return 'door-open'
    if any(x in n for x in ['terraza', 'jardin', 'garden']): return 'trees'
    if any(x in n for x in ['24h', '24 horas', 'servicio']): return 'clock'
    if any(x in n for x in ['gimnasio', 'gym', 'ejercicio']): return 'activity'
    if any(x in n for x in ['cama', 'bed']): return 'bed-double'
    if any(x in n for x in ['vino', 'bar', 'drink']): return 'wine'
    if any(x in n for x in ['seguridad', 'caja fuerte', 'safe']): return 'shield'
    if any(x in n for x in ['musica', 'sonido', 'bocina']): return 'music'
    
    if current_icon in VALID_ICONS: return current_icon
    return 'star'

try:
    amenities = db.query(Amenity).all()
    count = 0
    for a in amenities:
        old_icon = a.icon
        new_icon = map_icon(a.name, a.icon)
        if old_icon != new_icon:
            print(f"Mapping '{a.name}': '{old_icon}' -> '{new_icon}'")
            a.icon = new_icon
            count += 1
            
    if count > 0:
        db.commit()
        print(f"Successfully updated {count} amenities with improved logic.")
    else:
        print("All amenities already have valid icons.")
finally:
    db.close()

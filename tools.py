import os
import io
import requests
import base64
from PIL import Image
from datetime import datetime, timedelta

# Company Database
VENUES = [
    {"name": "Grand Ballroom", "type": "indoor", "capacity": 500, "features": "Stage, AV, Luxury", "image_file": "indoor01.jpg"},
    {"name": "Glass Conservatory", "type": "indoor", "capacity": 200, "features": "Natural light, AC, Garden views", "image_file": "indoor02.jpg"},
    {"name": "Boutique Hall", "type": "indoor", "capacity": 150, "features": "Rustic, Dancefloor, Intimate", "image_file": "indoor03.jpg"},
    {"name": "Rooftop Seoul", "type": "outdoor", "capacity": 100, "features": "Ideal for Community-Led Events, Relaxed Social Environment, Rooftop, Speakeasy, Bar, Edgy", "image_file": "indoor04.jpg"},
    {"name": "Corporate Boardroom", "type": "indoor", "capacity": 50, "features": "Projector, Quiet, Executive", "image_file": "indoor5.jpeg"},
    {"name": "The Grey Box", "type": "indoor", "capacity": 200, "features": "Multi-functional event space, Easy access to public transportation", "image_file": "They Grey Box.jpg"},
    {"name": "Elegant Rooftop Venue", "type": "indoor", "capacity": 350, "features": "Projector, Quiet, Executive", "image_file": "Elegant Rooftop Venue.jpg"},
    {"name": "The Scole Inn Hotel", "type": "outdoor", "capacity": 250, "features": "Listed Building, Wedding Coordinator, Parking, Pet Friendly, Exclusive Use, Outdoor Reception Space, Landscaped Gardens, Ballroom", "image_file": "The Scole Inn Hotel.jpg"},
    {"name": "Horning's Hideout", "type": "outdoor", "capacity": 700, "features": "Lakeside Venue, Wooden Stage, Dance Floor, Dressing Room, Restrooms, Electricity, Private Camping", "image_file": "Horning's Hideout.jpg"},
    {"name": "The Hilltop Garden", "type": "outdoor", "capacity": 350, "features": "Natural Grass, KL Skyline View, Lush Greenery, Garden Venue", "image_file": "The Hilltop Garden.jpg"}    
]

BOOKED_DATES = {
    "Horning's Hideout": ["27/09/2026"], 
    "Lakeside Pavilion": ["15/10/2026"], 
    "Grand Ballroom": ["25/12/2026", "12/12/2026"],
    "Glass Conservatory": ["20/11/2026"]
}   

def get_alternative_dates(venue_name: str, requested_date_str: str) -> list:
    """Calculates the next 3 available days for a specific venue."""
    try:
        # Parse using the new DD/MM/YYYY format
        req_date = datetime.strptime(requested_date_str, "%d/%m/%Y")
        alts = []
        for i in range(1, 4):
            # Output using the new DD/MM/YYYY format
            alt_date = (req_date + timedelta(days=i)).strftime("%d/%m/%Y")
            if alt_date not in BOOKED_DATES.get(venue_name, []):
                alts.append(alt_date)
        return alts
    except Exception as e:
        return []

def get_alternative_venues(requested_venue_name: str, requested_date: str, capacity_needed: int, prefer_outdoor: bool) -> list:
    """
    Finds alternative venues available on the requested date.
    Calculates capacity differences and environment trade-offs so the user
    can pick a manageable substitute even if it's not an exact match.
    """
    alternatives = []
    
    for v in VENUES:
        if v["name"] == requested_venue_name:
            continue
            
        booked_dates = BOOKED_DATES.get(v["name"], [])
        if requested_date in booked_dates:
            continue  # Not available on this date
            
        # 1. Calculate capacity trade-off
        cap_diff = v["capacity"] - capacity_needed
        if cap_diff >= 0:
            cap_note = f"+{cap_diff} seats (fits all {capacity_needed} guests with extra room)"
        elif abs(cap_diff) <= 30:
            cap_note = f"{cap_diff} seats (cap is {v['capacity']}, close and manageable)"
        else:
            cap_note = f"{cap_diff} seats (cap is {v['capacity']}, tighter fit)"

        # 2. Calculate environment difference
        env_match = (v["type"] == "outdoor") == prefer_outdoor
        if env_match:
            env_note = f"Matches {v['type'].title()} preference"
        else:
            env_note = f"{v['type'].title()} space (Requested: {'Outdoor' if prefer_outdoor else 'Indoor'})"

        alternatives.append({
            "name": v["name"],
            "capacity": v["capacity"],
            "type": v["type"],
            "features": v.get("features", ""),
            "diff_note": f"{cap_note} • {env_note}",
            "capacity_diff": abs(cap_diff)
        })

    # Rank alternatives by closest capacity to the requested count
    alternatives.sort(key=lambda x: x["capacity_diff"])
    return alternatives


def search_venue_logic(capacity_needed: int, prefer_outdoor: bool, requested_date: str, requested_venue_name: str = None) -> dict:
    """Finds best matching venue, handling availability, explicit user choices, and rich alternatives."""
    
    # IF USER EXPLICITLY CHOSE A VENUE (Via Prompt or "Choose" Button)
    if requested_venue_name:
        candidates = [v for v in VENUES if requested_venue_name.lower() in v['name'].lower()]
        if candidates:
            best_venue = candidates[0]
        else:
            best_venue = VENUES[0] # Safe fallback
            
    # DEFAULT LOGIC (If no venue is explicitly named)
    else:
        preferred_type = "outdoor" if prefer_outdoor else "indoor"
        candidates = [v for v in VENUES if v['type'] == preferred_type and v['capacity'] >= capacity_needed]

        if not candidates:
            candidates = [v for v in VENUES if v['capacity'] >= capacity_needed]
        if not candidates:
            candidates = VENUES

        candidates.sort(key=lambda x: x['capacity'])
        best_venue = candidates[0]

    # Check for conflicts
    if requested_date in BOOKED_DATES.get(best_venue['name'], []):
        alt_dates = get_alternative_dates(best_venue['name'], requested_date)
        alt_venues = get_alternative_venues(
            requested_venue_name=best_venue['name'],
            requested_date=requested_date,
            capacity_needed=capacity_needed,
            prefer_outdoor=prefer_outdoor
        )
        return {
            "status": "Conflict",
            "venue": best_venue,
            "alt_dates": alt_dates,
            "alt_venues": alt_venues,
            "message": f"Conflict: {best_venue['name']} is booked on {requested_date}."
        }

    return {
        "status": "Success",
        "venue": best_venue,
        "message": f"Successfully reserved {best_venue['name']} on {requested_date}."
    }

def build_staging_prompt(theme: str, pax: int, request_text: str, is_outdoor: bool) -> tuple[str, str]:
    """
    Builds a highly detailed positive prompt and negative prompt for Stability AI
    that guarantees empty rooms are populated with furniture according to capacity,
    event type, and cultural requirements.
    """
    text_lower = request_text.lower()
    
    # 1. Cultural & Event Motifs
    cultural_decor = ""
    if any(k in text_lower for k in ["malay", "kahwin", "nikah", "sanding"]):
        cultural_decor = (
            "featuring an ornate grand Pelamin bridal dais with draped silk, floral arches, "
            "warm ambient chandeliers, traditional bunga manggar accents, and an elevated VIP Meja Beradab dining table"
        )
    elif any(k in text_lower for k in ["chinese", "cny", "tea ceremony"]):
        cultural_decor = (
            "styled with festive red, champagne, and gold satin fabrics, large 10-seater round tables "
            "with lazy susan centerpieces, hanging lanterns, and an elegant celebration stage backdrop"
        )
    elif any(k in text_lower for k in ["indian", "mandap", "sangeet", "diwali"]):
        cultural_decor = (
            "featuring a rich mandap stage framed with fresh marigold and jasmine garlands, "
            "vibrant jewel-toned drapes, brass oil lamps (diya), and opulent banquet table runners"
        )
    elif any(k in text_lower for k in ["corporate", "conference", "summit", "launch", "boardroom"]):
        cultural_decor = (
            "fitted with a sleek keynote presentation stage, widescreen AV projection backdrop, "
            "podium, executive place settings, and focused directional stage lighting"
        )
    elif any(k in text_lower for k in ["cyberpunk", "futuristic", "neon", "party"]):
        cultural_decor = (
            "illuminated with dramatic neon LED strip lighting, glow-in-the-dark centerpieces, "
            "ambient cocktail lounge furniture, high-top bar tables, and modern metallic backdrops"
        )
    else:
        cultural_decor = (
            "decorated with high-end festive drapery, fresh floral arrangements, "
            "luxury table linens, and a focal celebration backdrop"
        )

    # 2. Capacity-Based Seating & Furniture Arrangement
    if pax <= 40:
        furniture_layout = (
            f"fully furnished for an intimate gathering of {pax} guests with premium dining tables, "
            "cushioned designer chairs, formal cutlery settings, floral centerpieces, and clear aisles"
        )
    elif pax <= 150:
        furniture_layout = (
            f"densely furnished banquet floor populated with multiple dressed round banquet tables, "
            f"matching Chiavari chairs neatly arranged to seat {pax} people, full tableware, centerpieces, and walkways"
        )
    else:
        furniture_layout = (
            f"grand high-capacity banquet hall arrangement filled with dozens of round dining tables and chairs "
            f"scaled to accommodate a large crowd of {pax} guests, with clear service aisles and unobstructed stage sightlines"
        )

    # 3. Setting & Atmosphere
    setting = "Outdoor manicured lawn and garden venue" if is_outdoor else "Indoor ballroom event space"
    
    positive_prompt = (
        f"{setting} fully transformed and staged for a {theme} event. "
        f"The venue is {furniture_layout}, {cultural_decor}. "
        "Warm festive ambient event lighting, wide-angle interior architectural photography, "
        "masterpiece, highly detailed, photorealistic, 8k resolution."
    )

    # 4. Mandatory Negative Prompt to Eliminate Empty Floors
    negative_prompt = (
        "empty room, vacant room, bare floor, unfurnished, deserted hall, empty dance floor, "
        "missing tables, missing chairs, empty hall, desolate space, unfinished venue, "
        "distorted furniture, floating objects, blurry, low resolution, bad perspective, cartoon"
    )

    return positive_prompt, negative_prompt


def edit_venue_picture(base_image_filename: str, theme: str, pax: int, request_text: str = "") -> str:
    """
    Uses Stability AI (SDXL) Image-to-Image to transform and furnish base venue images.
    """
    from dotenv import load_dotenv
    import os
    import io
    import requests
    import base64
    from PIL import Image

    input_path = os.path.join("images", base_image_filename)
    output_filename = f"ai_edited_{base_image_filename.split('.')[0]}.png"
    output_path = os.path.join("images", output_filename)

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Local picture not found at: {input_path}")

    load_dotenv(override=True)
    api_key = os.getenv("STABILITY_API_KEY")

    if not api_key or api_key.strip() == "" or api_key.startswith("#"):
        return base_image_filename

    # Check environment (indoor vs outdoor) from database
    venue_info = next((v for v in VENUES if v.get("image_file") == base_image_filename), None)
    is_outdoor = venue_info.get("type") == "outdoor" if venue_info else False

    # Generate custom positive and negative prompts
    pos_prompt, neg_prompt = build_staging_prompt(
        theme=theme,
        pax=pax,
        request_text=request_text,
        is_outdoor=is_outdoor
    )

    try:
        img = Image.open(input_path).convert("RGB")
        width, height = img.size

        if width > height:
            target_size = (1344, 768)
        elif height > width:
            target_size = (768, 1344)
        else:
            target_size = (1024, 1024)

        img = img.resize(target_size, Image.Resampling.LANCZOS)

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")
        img_bytes = img_byte_arr.getvalue()

        response = requests.post(
            "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/image-to-image",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            files={
                "init_image": ("image.png", img_bytes, "image/png")
            },
            data={
                "init_image_mode": "IMAGE_STRENGTH",
                # 0.44 allows SDXL to paint over bare floors with tables while
                # keeping original room architecture, windows, and perimeter intact
                "image_strength": 0.44,
                "text_prompts[0][text]": pos_prompt,
                "text_prompts[0][weight]": 1.0,
                "text_prompts[1][text]": neg_prompt,
                "text_prompts[1][weight]": -1.0,
                "cfg_scale": 11,
                "samples": 1,
                "steps": 30,
            }
        )

        if response.status_code != 200:
            try:
                error_details = response.json().get("message", response.text)
            except Exception:
                error_details = response.text

            if response.status_code in [402, 403]:
                raise RuntimeError(f"API TOKEN DEPLETED: Stability credits exhausted (Code {response.status_code}).")
            elif response.status_code == 401:
                raise RuntimeError(f"UNAUTHORIZED: Stability API key is invalid (Code {response.status_code}).")
            else:
                raise RuntimeError(f"STABILITY API ERROR (Code {response.status_code}): {error_details}")

        data = response.json()
        for image in data["artifacts"]:
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(image["base64"]))

        return output_filename

    except Exception as e:
        raise Exception(f"{str(e)}")
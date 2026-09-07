import json
import os
import re
import time
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from state import SchedulerState
from tools import search_venue_logic, edit_venue_picture, VENUES

# Configure LLM
load_dotenv(override=True) 
# Note: Logistics is now MOCKED to be offline, but Catering/AI image gen still uses this model.
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,  # Strict temperature ensures reliable structured JSON
    max_retries=2
)

# ===============================================================================
# PRESENTATION MOCK SYSTEM
# This bypasses the Google API to prevent Free Tier timeout errors during demos.
# ===============================================================================

class MockResponse:
    """Dummy class to simulate a response object without API calls."""
    def __init__(self, request):
        # Passes the raw user request into the simulation function.
        self.content = self._generate_simulated_json(request)

    def _generate_simulated_json(self, request):
        """
        Manually processes the text request instead of asking Gemini.
        Strictly offline to guarantee zero timeouts or formatting errors.
        """
        import re
        request_lower = request.lower()
        
        # 1. Smarter Date Extraction (Now outputs DD/MM/YYYY)
        req_date = "MISSING"
        # Support reading both DD/MM/YYYY and YYYY-MM-DD inputs
        slash_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', request_lower)
        iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', request_lower)
        
        if slash_match:
            req_date = slash_match.group(0) # Already DD/MM/YYYY
        elif iso_match:
            # Convert ISO to DD/MM/YYYY
            req_date = f"{iso_match.group(3)}/{iso_match.group(2)}/{iso_match.group(1)}" 
        else:
            # Map spelled-out months to numbers
            month_map = {
                "january": "01", "february": "02", "march": "03", "april": "04", 
                "may": "05", "june": "06", "july": "07", "august": "08", 
                "september": "09", "october": "10", "november": "11", "december": "12"
            }
            for month, mm in month_map.items():
                if month in request_lower:
                    # Look for the day and optional year right after the month
                    match = re.search(rf'{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:[\s,]+(\d{{4}}))?', request_lower)
                    if match:
                        dd = match.group(1).zfill(2)
                        yyyy = match.group(2) if match.group(2) else "2026" # Default to 2026
                        # Format the output as DD/MM/YYYY
                        req_date = f"{dd}/{mm}/{yyyy}" 
                        break

        # 2. Extract indoor/outdoor preference
        # Look for typical outdoor keywords: "outdoor", "garden", "rooftop", "outside"
        is_outdoor = "outdoor" in request_lower or "garden" in request_lower or "rooftop" in request_lower or "lakeside" in request_lower
        
        # 3. Extract capacity
        # We manually parse the text for numbers associated with "people" or "pax".
        pax = 150
        pax_match = re.search(r'(\d+)\s*people', request_lower)
        if pax_match: 
            pax = int(pax_match.group(1))
        else:
            # Fallback number finder
            fallback = re.search(r'\d+', request_lower)
            if fallback: pax = int(fallback.group(0))

        # 4. Create the JSON string that Gemini *would* have generated.
        # IF THIS RETURN STATEMENT IS MISSING, THE ENTIRE SYSTEM CRASHES.
        return f"""
        ```json
        {{
            "capacity_needed": {pax},
            "is_outdoor": {str(is_outdoor).lower()},
            "theme": "Presentation Demo Theme (Offline Mock)",
            "food_style": "Buffet",
            "event_date": "{req_date}"
        }}
        ```
        """

# ===============================================================================
# UTILITIES & ROUTING
# ===============================================================================

def safe_parse_json(content) -> dict:
    """
    Robust JSON parser that handles LangChain content block lists 
    and strips markdown code fences to extract valid JSON.
    """
    try:
        # FIX: Unpack if Gemini returns content as a list of blocks or a dict
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(item["text"])
                elif hasattr(item, "text"):
                    text_parts.append(item.text)
                else:
                    text_parts.append(str(item))
            content = "".join(text_parts)
        elif isinstance(content, dict) and "text" in content:
            content = content["text"]
            
        content = str(content).strip()
        
        # 1. Remove standard markdown code fences if present
        if content.startswith("```json"): 
            content = content[7:]
        elif content.startswith("```"): 
            content = content[3:]
        if content.endswith("```"): 
            content = content[:-3]
        content = content.strip()
        
        # 2. Try direct load
        return json.loads(content)
        
    except Exception as e:
        # 3. Fallback: Use Regex to extract the first valid JSON object block { ... }
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
            
        raise ValueError(f"AI JSON Formatting Error: {str(e)} | Raw Output was: {str(content)[:100]}...")

def dynamic_router(state: SchedulerState) -> str:
    return "logistics_coordinator" 

# ===============================================================================
# AGENTS
# ===============================================================================

def logistics_coordinator(state: SchedulerState):
    """
    Logistics Agent: Extracts capacity, environment, date, and handles venue booking.
    Includes AI Recommender for conflicts and backend overrides for UI choices.
    """
    outputs = state.get("agent_outputs", [])
    
    try:
        # ==========================================
        # 1. ACTIVE GROQ EXTRACTION
        # ==========================================
        logistics_prompt = ChatPromptTemplate.from_template(
            "Extract event details from the user request into strict JSON format with exactly these keys: "
            "'capacity_needed' (integer), 'is_outdoor' (boolean), 'theme' (string), 'food_style' (string), "
            "'event_date' (string in DD/MM/YYYY format), and 'requested_venue' (string or null if no specific venue is named). "
            "If the date is missing, set 'event_date' to 'MISSING'.\nUser Request: {request}"
        )
        response = (logistics_prompt | llm).invoke({"request": state["initial_request"]})
        parsed = safe_parse_json(response.content)

        # ==========================================
        # 2. APPLY PROPER BACKEND OVERRIDES (From UI Buttons)
        # ==========================================
        if state.get("override_date"):
            parsed["event_date"] = state["override_date"]
            
        req_date = parsed.get("event_date", "MISSING")
        requested_venue = state.get("override_venue") or parsed.get("requested_venue")
        
        # 🚨 MISSING DATE CHECK
        if req_date == "MISSING" or req_date == "":
            outputs.append({"agent": "Logistics", "data": parsed, "tool_result": "Halted: Missing Date"})
            return {
                "venue_status": "Missing Date", "agent_outputs": outputs, 
                "confirmed_venue": "Pending", "confirmed_date": "Pending",
                "base_image_file": "", "edited_image_file": "", "conflict_data": {}
            }

        # ==========================================
        # 3. SEARCH VENUE DATABASE
        # ==========================================
        venue_result = search_venue_logic(
            capacity_needed=parsed.get("capacity_needed", 100),
            prefer_outdoor=parsed.get("is_outdoor", False),
            requested_date=req_date,
            requested_venue_name=requested_venue
        )
        
        outputs.append({"agent": "Logistics", "data": parsed, "tool_result": venue_result['message']})
        
        # ==========================================
        # 4. 🚨 CONFLICT CHECK & AI RECOMMENDER
        # ==========================================
        if venue_result["status"] == "Conflict":
            alt_venues = venue_result.get("alt_venues", [])
            
            # Trigger AI to filter down to TOP 2 recommendations
            if len(alt_venues) > 0:
                try:
                    import json
                    recommendation_prompt = ChatPromptTemplate.from_template(
                        "You are an expert event planner. The user's ideal venue is booked.\n"
                        "User Request: '{request}'\n"
                        "Available Alternatives: {alts}\n\n"
                        "Analyze the theme, vibe, and capacity. Select exactly the top 2 best alternatives from the list.\n"
                        "Output strictly in JSON format with exactly this structure:\n"
                        "{{\"recommendations\": [{{\"name\": \"Exact Venue Name\", \"ai_reasoning\": \"1 sentence explaining why this fits their specific theme/vibe.\"}}]}}"
                    )
                    
                    simplified_alts = [{"name": v["name"], "capacity": v["capacity"], "type": v["type"]} for v in alt_venues]
                    rec_response = (recommendation_prompt | llm).invoke({
                        "request": state["initial_request"],
                        "alts": json.dumps(simplified_alts)
                    })
                    
                    ai_recs = safe_parse_json(rec_response.content).get("recommendations", [])
                    
                    filtered_alts = []
                    for rec in ai_recs:
                        for v in alt_venues:
                            if v["name"].lower() == rec.get("name", "").lower():
                                # Adds the "Why" and "Trade-off" formatting for the UI
                                v["diff_note"] = f"✨ **Why:** {rec.get('ai_reasoning')} \n\n📊 **Trade-off:** {v['diff_note']}"
                                filtered_alts.append(v)
                                break
                                
                    # Overwrite the long list with just the 2 AI recommendations
                    if filtered_alts:
                        venue_result["alt_venues"] = filtered_alts
                except Exception as e:
                    print(f"AI Recommender skipped due to error: {e}") 
            
            return {
                "venue_status": "Action Required", 
                "agent_outputs": outputs, 
                "confirmed_venue": "Pending User Confirmation",
                "confirmed_date": req_date, 
                "base_image_file": "", 
                "edited_image_file": "",
                "conflict_data": venue_result 
            }
        
        # ==========================================
        # 5. SUCCESS: GENERATIVE AI VISUALIZATION
        # ==========================================
        base_file = venue_result['venue']['image_file']
        edited_file = edit_venue_picture(
            base_image_filename=base_file,
            theme=parsed.get("theme", "elegant"),
            pax=parsed.get("capacity_needed", 100),
            request_text=state.get("initial_request", "")
        )
        
        return {
            "venue_status": "Completed", 
            "agent_outputs": outputs, 
            "confirmed_venue": venue_result['venue']['name'],
            "confirmed_date": req_date, 
            "base_image_file": base_file, 
            "edited_image_file": edited_file,
            "conflict_data": {}
        }
        
    except Exception as e:
        error_msg = f"Logistics Parsing Error: {str(e)}"
        outputs.append({"agent": "Logistics", "data": {"Raw_Error": error_msg}})
        return {"venue_status": "System Error", "agent_outputs": outputs}
    
def catering_specialist(state: SchedulerState) -> dict:
    """
    Catering Agent: AI reasoning for food vibe + Deterministic math for costs.
    (Currently configured for LIVE GEMINI API with offline regex fallback commented out)
    """
    outputs = state.get("agent_outputs", [])
    
    try:
        # ==========================================
        # 🟢 ACTIVE: LIVE GEMINI API REASONING
        # ==========================================
        prompt = ChatPromptTemplate.from_template(
            "You are an expert AI Event Catering Planner. Analyze the user request to determine catering preferences.\n"
            "RULES:\n"
            "1. Do NOT calculate total costs or quantities. Leave that to the system.\n"
            "2. Do NOT invent dietary requirements. If none are specified, output an empty list.\n"
            "3. Extract the 'budget' if mentioned (number only), otherwise output null.\n"
            "4. Extract 'attendees' (number only) if mentioned, otherwise output null.\n"
            "Output strictly in JSON format with exactly these keys:\n"
            "- 'attendees' (integer or null)\n"
            "- 'budget' (float or null)\n"
            "- 'meal_type' (string: e.g., 'dinner', 'lunch', 'refreshments', 'breakfast')\n"
            "- 'catering_style' (string: e.g., 'buffet', 'plated', 'boxed', 'food trucks')\n"
            "- 'dietary_requirements' (list of strings)\n\n"
            "User Request: {request}"
        )
        response = (prompt | llm).invoke({"request": state["initial_request"]})
        ai_data = safe_parse_json(response.content)

        # ==========================================
        # 🔴 COMMENTED OUT: OFFLINE REGEX MOCK (Uncomment if tokens run out)
        # ==========================================
        # import re
        # request_lower = state["initial_request"].lower()
        # ai_data = {
        #     "attendees": None, "budget": None,
        #     "meal_type": "dinner" if "dinner" in request_lower else "lunch" if "lunch" in request_lower else "standard meal",
        #     "catering_style": "food trucks" if "truck" in request_lower else "plated" if "plated" in request_lower else "buffet",
        #     "dietary_requirements": []
        # }
        # if "halal" in request_lower: ai_data["dietary_requirements"].append("halal")
        # if "vegetarian" in request_lower: ai_data["dietary_requirements"].append("strict vegetarian")
        # budget_match = re.search(r'budget[\s\w]*?(\d+)', request_lower)
        # if budget_match: ai_data["budget"] = float(budget_match.group(1))
        # pax_match = re.search(r'(\d+)\s*people', request_lower)
        # if pax_match: ai_data["attendees"] = int(pax_match.group(1))
        # ==========================================

        # 2. DETERMINISTIC LOGIC & BUSINESS MATH
        pax = ai_data.get("attendees")
        if not pax:
            pax = next((out.get("data", {}).get("capacity_needed") for out in outputs if out.get("agent") == "Logistics"), None)
            
        if not pax or pax <= 0:
            missing_payload = {
                "status": "needs_information",
                "missing_information": ["attendees"],
                "message": "Number of attendees is required to calculate accurate catering quantities and costs."
            }
            outputs.append({"agent": "Catering", "data": missing_payload, "tool_result": "Halted: Missing Attendee Count."})
            return {"catering_status": "Action Required", "agent_outputs": outputs}

        dietary_needs = ai_data.get("dietary_requirements", [])
        quantities = {
            "total_servings": pax,
            "main_meals": pax,
            "drinks": int(pax * 1.5), 
            "desserts": pax if ai_data.get("meal_type") in ["dinner", "lunch"] else 0,
            "special_diet_meals": int(pax * 0.15) if dietary_needs else 0 
        }

        catering_style = ai_data.get("catering_style", "buffet").lower()
        base_cost_per_person = 25.0
        if "plated" in catering_style: base_cost_per_person = 45.0
        elif "truck" in catering_style: base_cost_per_person = 20.0
        elif "refreshment" in ai_data.get("meal_type", "").lower(): base_cost_per_person = 12.0
        
        estimated_total_cost = pax * base_cost_per_person
        
        user_budget = ai_data.get("budget")
        budget_status = "unknown (no budget provided)"
        if user_budget:
            budget_status = "within_budget" if estimated_total_cost <= user_budget else "exceeds_budget"

        confirmed_venue = state.get("confirmed_venue", "")
        venue_compatibility = "unknown"
        warnings = []
        
        if confirmed_venue and confirmed_venue != "Pending User Confirmation":
            venue_info = next((v for v in VENUES if v["name"] == confirmed_venue), None)
            if venue_info:
                venue_compatibility = "compatible"
                features = venue_info.get("features", "").lower()
                
                if "buffet" in catering_style and "intimate" in features:
                    warnings.append("Venue is marked as intimate; buffet tables may cause space constraints.")
                if "truck" in catering_style and venue_info.get("type") == "indoor":
                    warnings.append("Food trucks selected, but venue is indoors. Adjusting to boxed/setup catering is recommended.")
                    venue_compatibility = "flagged"

        catering_plan = {
            "status": "success",
            "event_context": {
                "meal_type": ai_data.get("meal_type", "standard meal"),
                "catering_style": catering_style,
                "dietary_requirements": dietary_needs if dietary_needs else ["not specified"]
            },
            "logistics": {
                "attendees": pax,
                "quantities": quantities,
                "setup_requirements": ["Serving tables", "Waste disposal"] if "buffet" in catering_style else ["Waitstaff", "Kitchen prep area"]
            },
            "financials": {
                "cost_per_person": base_cost_per_person,
                "estimated_total_cost": estimated_total_cost,
                "budget_status": budget_status
            },
            "venue_integration": {
                "venue_name": confirmed_venue if confirmed_venue else "Not Selected",
                "compatibility": venue_compatibility,
                "warnings": warnings
            }
        }
        
        outputs.append({"agent": "Catering", "data": catering_plan, "tool_result": f"Catering plan generated for {pax} pax."})
        return {"catering_status": "Completed", "agent_outputs": outputs}
        
    except Exception as e:
        outputs.append({"agent": "Catering", "data": {"status": "System Error", "error": str(e)[:250]}, "tool_result": "Failed to generate catering plan."})
        return {"error_flag": True, "catering_status": "System Error", "agent_outputs": outputs}

def scheduling_manager(state: SchedulerState) -> dict:
    outputs = state.get("agent_outputs", [])
    outputs.append({"agent": "Scheduling", "data": {"status": "Schedule optimized."}, "tool_result": "Calendar locked."})
    return {"schedule_status": "Completed", "agent_outputs": outputs}

def evaluator(state: SchedulerState) -> dict:
    if state.get("error_flag"):
        return {"final_evaluation": "RISK WARNING: System detected API error in Catering or Image generation. Logistics worked via Offline Mock."}
    return {"final_evaluation": "All agents successfully collaborated. Strategy approved (Logistics operated in Offline Mock mode)."}
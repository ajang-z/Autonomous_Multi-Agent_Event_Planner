import streamlit as st
import logging
import os
import re
from dotenv import load_dotenv

# 1. LOAD THE API KEYS FIRST!
load_dotenv(override=True)

# 2. THEN IMPORT THE GRAPH (Now Groq will find the key)
from graph import app 
from tools import VENUES

logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_PYTHON_LOG_LEVEL"] = "error"

st.set_page_config(page_title="AI Event Logistics & Catering Planner", layout="wide")
st.title("🎪 Autonomous Multi-Agent Event Planner")

# Initialize Clean Session States
if "request_text" not in st.session_state:
    st.session_state["request_text"] = "We need to plan an elegant floral indoor wedding for 150 people on 20/11/2026."
if "auto_run" not in st.session_state:
    st.session_state["auto_run"] = False
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
if "override_venue" not in st.session_state:
    st.session_state["override_venue"] = None
if "override_date" not in st.session_state:
    st.session_state["override_date"] = None

# Action handlers for Choose buttons
def select_date(new_date):
    current = st.session_state["request_text_area"]
    if re.search(r'\b\d{2}/\d{2}/\d{4}\b', current):
        updated_text = re.sub(r'\b\d{2}/\d{2}/\d{4}\b', new_date, current)
    else:
        updated_text = f"{current} on {new_date}"
    
    # 🟢 FIX: Directly update the widget's internal memory
    st.session_state["request_text_area"] = updated_text
    st.session_state["request_text"] = updated_text
    st.session_state["auto_run"] = True

def select_venue(new_venue_name):
    current = st.session_state["request_text_area"]
    updated_text = f"[SYSTEM DIRECTIVE: User explicitly chose venue '{new_venue_name}'. You MUST extract '{new_venue_name}' as requested_venue.]\n{current}"
    
    # 🟢 FIX: Directly update the widget's internal memory
    st.session_state["request_text_area"] = updated_text
    st.session_state["request_text"] = updated_text
    st.session_state["auto_run"] = True

# Main Request Input Area
# By relying strictly on the 'key', Streamlit keeps the UI and background variables perfectly synced
request_text = st.text_area(
    "Enter Requirements (Date in DD/MM/YYYY):", 
    key="request_text_area",
    height=100
)
st.session_state["request_text"] = st.session_state["request_text_area"]

run_pressed = st.button("Run Multi-Agent System", type="primary")
# ==========================================================
# 🟢 THE FIX: DYNAMIC UI PLACEHOLDER
# This empty container reserves space on the screen. 
# When "Choose" is clicked, it allows us to instantly wipe the UI.
# ==========================================================
output_placeholder = st.empty()

# Execute when user clicks button OR when a 'Choose' alternative is clicked
if run_pressed or st.session_state.get("auto_run"):
    st.session_state["auto_run"] = False
    st.session_state["last_result"] = None
    
    # 🟢 INSTANTLY WIPE THE CONFLICT OPTIONS FROM THE SCREEN
    output_placeholder.empty() 
    
    with st.status("🚀 Processing Multi-Agent Workflow...", expanded=True) as status:
        st.write("🕵️‍♂️ **Logistics Agent:** Checking venue availability and dates...")
        st.write("👨‍🍳 **Catering Agent:** Calculating meal style, capacity, and dietary needs...")
        st.write("🎨 **Image Engine:** Preparing visualization...")
        
        initial_input = {
            "initial_request": st.session_state["request_text"],
            "event_type": "", "venue_status": "Pending", "catering_status": "Pending",
            "schedule_status": "Pending", "error_flag": False, "final_evaluation": "",
            "agent_outputs": [], "confirmed_venue": "", "confirmed_date": "", 
            "base_image_file": "", "image_url": ""
        }
        
        try:
            st.session_state["last_result"] = app.invoke(initial_input)
            status.update(label="✅ Processing Complete!", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ System Crashed", state="error", expanded=True)
            st.error(f"Pipeline Crash: {str(e)}")
            st.stop()

# Render System Output INSIDE the dynamic placeholder
result = st.session_state.get("last_result")

if result:
    # Everything inside this 'with' block gets erased the moment output_placeholder.empty() is called above
    with output_placeholder.container():
        st.markdown("---")

        # Extract Catering Summary
        catering_summary = ""
        for out in result.get("agent_outputs", []):
            if "Catering" in out.get("agent", ""):
                c_data = out.get("data", {})
                if c_data.get("status") == "success":
                    style = c_data.get("event_context", {}).get("catering_style", "Standard").title()
                    pax = c_data.get("logistics", {}).get("attendees", 0)
                    cost = c_data.get("financials", {}).get("estimated_total_cost", 0)
                    warnings = c_data.get("venue_integration", {}).get("warnings", [])
                    
                    catering_summary = f"\n- 🍽️ **Catering Plan:** {style} for {pax} pax (Est. RM{cost:,.2f})"
                    if warnings:
                        catering_summary += f"\n- ⚠️ **Catering Note:** {warnings[0]}"
                break

        # MISSING DATE
        if result.get("venue_status") == "Missing Date":
            st.error("⚠️ **MISSING INFORMATION**")
            st.markdown("Please specify an event date in **DD/MM/YYYY** format (e.g., `20/11/2026`).")

        # CONFLICT RESOLUTION
        elif result.get("venue_status") == "Action Required":
            st.error("⚠️ **BOOKING CONFLICT DETECTED**")
            conflict = result.get("conflict_data", {})
            
            st.markdown(f"The best matching venue **{conflict['venue']['name']}** is **ALREADY BOOKED** on that date.")
            
            if catering_summary:
                st.info(f"**Preliminary Event Details:**{catering_summary}")

            st.markdown("### Choose an option below to proceed instantly:")
            
            colA, colB = st.columns(2)
            
            # Option A: Change Date
            with colA:
                st.markdown(f"#### 📅 Option A: Change Date (Keep {conflict['venue']['name']})")
                alt_dates = conflict.get("alt_dates", [])
                if alt_dates:
                    for d in alt_dates:
                        d_col1, d_col2 = st.columns([3, 1])
                        with d_col1:
                            st.write(f"🗓️ **{d}**")
                        with d_col2:
                            st.button("Choose", key=f"btn_d_{d}", on_click=select_date, args=(d,))
                else:
                    st.write("No nearby alternative dates found.")

            # Option B: Change Venue
            with colB:
                st.markdown("#### 🏢 Option B: Change Venue (Keep Date)")
                alt_venues = conflict.get("alt_venues", [])
                if alt_venues:
                    for v in alt_venues:
                        v_col1, v_col2 = st.columns([3, 1])
                        with v_col1:
                            st.markdown(f"**{v['name']}** ({v['type'].title()})")
                            st.caption(f"{v['diff_note']}")
                        with v_col2:
                            st.button("Choose", key=f"btn_v_{v['name']}", on_click=select_venue, args=(v['name'],))
                else:
                    st.write("No alternative venues are available on this date.")

        # SYSTEM ERROR
        elif result.get("venue_status") == "System Error":
            st.error("🚨 **SYSTEM ERROR**")
            for output in result.get("agent_outputs", []):
                data = output.get("data", {})
                if isinstance(data, dict) and "Raw_Error" in data:
                    st.error(f"Failed Agent: {output.get('agent')}")
                    st.json(data)

        # SUCCESS CONFIRMATION
        else:
            st.balloons()
            st.markdown("### 🔔 SYSTEM NOTIFICATION: EVENT CONFIRMATION")
            st.success(
                f"**Notification Alert:** Your event has been successfully reserved!\n\n"
                f"- 📍 **Confirmed Venue:** `{result.get('confirmed_venue')}`\n"
                f"- ⏰ **Confirmed Date:** `{result.get('confirmed_date')}`"
                f"{catering_summary}"
            )
            
            # Visualization Section
            st.subheader("🎨 Venue Visualization: Base vs. AI Themed Edit")
            img_col1, img_col2 = st.columns(2)
            with img_col1:
                base_image_file = result.get("base_image_file", "")
                if base_image_file:
                    base_path = os.path.join("images", base_image_file)
                    if os.path.isfile(base_path):
                        st.image(base_path, caption=f"Original Venue: {result.get('confirmed_venue')}", use_container_width=True)
            with img_col2:
                edited_file = result.get("edited_image_file", "")
                if edited_file:
                    edited_path = os.path.join("images", edited_file)
                    if os.path.isfile(edited_path):
                        st.image(edited_path, caption="AI Decorated Venue", use_container_width=True)

            # Agent Outputs
            st.markdown("---")
            with st.expander("🕵️ Agent Outputs & Execution Logs", expanded=False):
                for output in result.get("agent_outputs", []):
                    st.markdown(f"**Agent:** `{output['agent']}`")
                    st.json(output.get('data', {}))
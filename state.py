# state.py
from typing import Dict, TypedDict, Any, List, Optional

class SchedulerState(TypedDict):
    initial_request: str
    override_venue: Optional[str]
    override_date: Optional[str]
    event_type: str
    venue_status: str
    catering_status: str
    schedule_status: str
    error_flag: bool
    final_evaluation: str
    agent_outputs: List[Dict[str, Any]]
    confirmed_venue: str
    confirmed_date: str
    base_image_file: str  
    edited_image_file: str
    conflict_data: dict
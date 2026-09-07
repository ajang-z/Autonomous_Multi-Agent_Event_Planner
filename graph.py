# graph.py
from langgraph.graph import StateGraph, END
from state import SchedulerState
from agents import logistics_coordinator, catering_specialist, scheduling_manager, evaluator, dynamic_router

workflow = StateGraph(SchedulerState)

workflow.add_node("logistics_coordinator", logistics_coordinator)
workflow.add_node("catering_specialist", catering_specialist)
workflow.add_node("scheduling_manager", scheduling_manager)
workflow.add_node("evaluator", evaluator)

workflow.set_conditional_entry_point(
    dynamic_router,
    {
        "logistics_coordinator": "logistics_coordinator",
        "catering_specialist": "catering_specialist",
        "scheduling_manager": "scheduling_manager"
    }
)

workflow.add_edge("logistics_coordinator", "catering_specialist")
workflow.add_edge("catering_specialist", "scheduling_manager")
workflow.add_edge("scheduling_manager", "evaluator")
workflow.add_edge("evaluator", END)

app = workflow.compile()
"""
Agent registry - export all agents from a single entry point.

Available agents:
	investment        - equity research analyst (InvestmentAgent)
	policy_monitoring - regulatory intelligence analyst (PolicyMonitoringAgent)
"""
from agent.investment.loop import run_analysis as investment_run_analysis
from agent.policy_monitoring import PolicyMonitoringAgent

__all__ = ["investment_run_analysis", "PolicyMonitoringAgent"]

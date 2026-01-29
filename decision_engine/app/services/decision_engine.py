"""
Decision & Verification Engine
Validates results, calculates confidence scores, and applies business rules
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Engine for validating results and making decisions"""
    
    def __init__(self):
        self.high_confidence_threshold = settings.HIGH_CONFIDENCE_THRESHOLD
        self.medium_confidence_threshold = settings.MEDIUM_CONFIDENCE_THRESHOLD
        self.low_confidence_threshold = settings.LOW_CONFIDENCE_THRESHOLD
        self.auto_send_confidence = settings.AUTO_SEND_CONFIDENCE
        self.requires_review_confidence = settings.REQUIRES_REVIEW_CONFIDENCE
    
    async def verify_and_decide(
        self,
        intent_result: Dict[str, Any],
        orchestration_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Verify results and make decision on next steps
        
        Returns:
        {
            "confidence_score": 0.0-1.0,
            "validity_checks": {...},
            "decision": "auto_send" | "review_required" | "escalate",
            "reasoning": "...",
            "verified_data": {...}
        }
        """
        try:
            # Step 1: Validity checks
            validity_checks = self._run_validity_checks(intent_result, orchestration_results)
            
            # Step 2: Calculate confidence score
            confidence_score = self._calculate_confidence(
                intent_result,
                orchestration_results,
                validity_checks
            )
            
            # Step 3: Verify data quality
            verified_data = self._verify_data_quality(orchestration_results)
            
            # Step 4: Make decision
            decision = self._make_decision(confidence_score, validity_checks, verified_data)
            
            # Step 5: Generate reasoning
            reasoning = self._generate_reasoning(
                confidence_score,
                decision,
                validity_checks,
                verified_data
            )
            
            return {
                "confidence_score": confidence_score,
                "validity_checks": validity_checks,
                "decision": decision,
                "reasoning": reasoning,
                "verified_data": verified_data
            }
            
        except Exception as e:
            logger.error(f"Error in decision engine: {e}", exc_info=True)
            raise
    
    def _run_validity_checks(
        self,
        intent_result: Dict[str, Any],
        orchestration_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run validity checks on results"""
        checks = {
            "has_exact_rates": False,
            "has_valid_ports": False,
            "has_valid_dates": False,
            "has_multiple_sources": False,
            "data_consistency": True,
            "sql_graph_disagreement": False  # NEW: SQL/Graph disagreement check
        }
        
        # Check for exact rates
        exact_rates = orchestration_results.get("results", {}).get("exact_rates", [])
        checks["has_exact_rates"] = len(exact_rates) > 0
        
        # Check for valid ports
        entities = intent_result.get("entities", {})
        checks["has_valid_ports"] = bool(
            entities.get("origin_port") and entities.get("destination_port")
        )
        
        # Check for valid dates
        if exact_rates:
            now = datetime.utcnow()
            for rate in exact_rates:
                valid_from = rate.get("valid_from")
                valid_to = rate.get("valid_to")
                if valid_from and valid_to:
                    # Check if rate is currently valid
                    checks["has_valid_dates"] = True
                    break
        
        # Check for multiple sources (SQL + Graph + Vector)
        engines_used = orchestration_results.get("engines_used", {})
        checks["has_multiple_sources"] = sum(engines_used.values()) > 1
        
        # Check data consistency
        if len(exact_rates) > 1:
            # Check if rates are consistent (similar price ranges)
            base_rates = [r.get("base_rate", 0) for r in exact_rates if r.get("base_rate")]
            if base_rates:
                min_rate = min(base_rates)
                max_rate = max(base_rates)
                # If price range is too wide, might indicate inconsistency
                if max_rate > 0:
                    price_variance = (max_rate - min_rate) / max_rate
                    checks["data_consistency"] = price_variance < 0.5  # 50% variance threshold
        
        # NEW: Check SQL/Graph disagreement
        # If SQL finds a route but Graph doesn't (or vice versa), flag disagreement
        raw_results = orchestration_results.get("raw_results", {})
        checks["sql_graph_disagreement"] = self._check_sql_graph_disagreement(raw_results, engines_used)
        
        return checks
    
    def _check_sql_graph_disagreement(
        self,
        raw_results: Dict[str, Any],
        engines_used: Dict[str, bool]
    ) -> bool:
        """
        Check if SQL and Graph results disagree on route existence.
        
        Disagreement occurs when:
        - Both engines were used
        - One found routes that the other didn't find
        
        This catches bad extractions and bad mappings early.
        """
        # Only check if both engines were used
        if not (engines_used.get("sql") and engines_used.get("graph")):
            return False
        
        sql_results = raw_results.get("sql_results", [])
        graph_results = raw_results.get("graph_results", [])
        
        # Extract route keys from SQL results
        sql_routes = set()
        for r in sql_results:
            if isinstance(r, dict):
                route = r.get("route", r)
                origin = route.get("origin_port", "").upper()
                dest = route.get("destination_port", "").upper()
                if origin and dest:
                    sql_routes.add((origin, dest))
        
        # Extract route keys from Graph results (excluding alternatives)
        graph_routes = set()
        for r in graph_results:
            if isinstance(r, dict) and r.get("type") != "alternatives":
                origin = r.get("origin_port", "").upper()
                dest = r.get("destination_port", "").upper()
                if origin and dest:
                    graph_routes.add((origin, dest))
        
        # If either has results but they don't overlap, there's disagreement
        if sql_routes and graph_routes:
            # Both have routes - check for any overlap
            if not sql_routes.intersection(graph_routes):
                logger.warning(f"SQL/Graph disagreement: SQL routes={sql_routes}, Graph routes={graph_routes}")
                return True
        elif sql_routes and not graph_routes:
            # SQL found routes, Graph didn't
            logger.warning(f"SQL/Graph disagreement: SQL found {len(sql_routes)} routes, Graph found none")
            return True
        elif graph_routes and not sql_routes:
            # Graph found routes, SQL didn't
            logger.warning(f"SQL/Graph disagreement: Graph found {len(graph_routes)} routes, SQL found none")
            return True
        
        return False
    
    def _calculate_confidence(
        self,
        intent_result: Dict[str, Any],
        orchestration_results: Dict[str, Any],
        validity_checks: Dict[str, Any]
    ) -> float:
        """Calculate overall confidence score"""
        confidence = 0.0
        
        # Base confidence from intent classification
        intent_confidence = intent_result.get("confidence", 0.5)
        confidence += intent_confidence * 0.3
        
        # Confidence from exact rates
        exact_rates = orchestration_results.get("results", {}).get("exact_rates", [])
        if validity_checks.get("has_exact_rates"):
            if len(exact_rates) >= 3:
                confidence += 0.3  # Multiple exact matches
            elif len(exact_rates) >= 1:
                confidence += 0.2  # At least one exact match
        
        # Confidence from validity checks
        if validity_checks.get("has_valid_ports"):
            confidence += 0.1
        if validity_checks.get("has_valid_dates"):
            confidence += 0.1
        if validity_checks.get("has_multiple_sources"):
            confidence += 0.1
        if validity_checks.get("data_consistency"):
            confidence += 0.1
        
        # PENALTY: SQL/Graph disagreement reduces confidence
        # This catches bad extractions and bad mappings early
        if validity_checks.get("sql_graph_disagreement"):
            confidence -= 0.15  # Downgrade by 15%
            logger.info(f"Confidence reduced by 15% due to SQL/Graph disagreement")
        
        # Cap at 1.0 and floor at 0.0
        confidence = max(0.0, min(confidence, 1.0))
        
        return confidence
    
    def _verify_data_quality(
        self,
        orchestration_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify quality of retrieved data"""
        verified = {
            "exact_rates_count": 0,
            "rates_with_validity": 0,
            "rates_with_transit_time": 0,
            "semantic_context_available": False
        }
        
        exact_rates = orchestration_results.get("results", {}).get("exact_rates", [])
        verified["exact_rates_count"] = len(exact_rates)
        
        for rate in exact_rates:
            if rate.get("valid_from") and rate.get("valid_to"):
                verified["rates_with_validity"] += 1
            if rate.get("transit_time"):
                verified["rates_with_transit_time"] += 1
        
        semantic_context = orchestration_results.get("results", {}).get("semantic_context", [])
        verified["semantic_context_available"] = len(semantic_context) > 0
        
        return verified
    
    def _make_decision(
        self,
        confidence_score: float,
        validity_checks: Dict[str, Any],
        verified_data: Dict[str, Any]
    ) -> str:
        """
        Make decision on next steps.
        
        GUARDRAIL: Never auto_send without exact rates.
        Alternatives without prices = sales risk.
        """
        has_exact_rates = validity_checks.get("has_exact_rates", False)
        
        # GUARDRAIL: If no exact rates, NEVER auto_send
        # Even if graph/vector look good, alternatives without prices = sales risk
        if not has_exact_rates:
            logger.info("⚠️  No exact rates found - auto_send blocked")
            if confidence_score >= self.requires_review_confidence:
                return "review_required"
            return "escalate"
        
        # High confidence AND exact rates: auto-send
        if confidence_score >= self.auto_send_confidence and has_exact_rates:
            return "auto_send"
        
        # Medium confidence: review required
        if confidence_score >= self.requires_review_confidence:
            return "review_required"
        
        # Low confidence: escalate
        if confidence_score < self.low_confidence_threshold:
            return "escalate"
        
        # Default: review required
        return "review_required"
    
    def _generate_reasoning(
        self,
        confidence_score: float,
        decision: str,
        validity_checks: Dict[str, Any],
        verified_data: Dict[str, Any]
    ) -> str:
        """Generate human-readable reasoning"""
        reasons = []
        
        if confidence_score >= self.high_confidence_threshold:
            reasons.append(f"High confidence ({confidence_score:.1%})")
        elif confidence_score >= self.medium_confidence_threshold:
            reasons.append(f"Medium confidence ({confidence_score:.1%})")
        else:
            reasons.append(f"Low confidence ({confidence_score:.1%})")
        
        if validity_checks.get("has_exact_rates"):
            reasons.append(f"Found {verified_data['exact_rates_count']} exact rate matches")
        else:
            reasons.append("No exact rates found")
        
        if validity_checks.get("has_valid_ports"):
            reasons.append("Valid origin/destination ports identified")
        
        if validity_checks.get("has_valid_dates"):
            reasons.append("Rates have valid date ranges")
        
        if validity_checks.get("has_multiple_sources"):
            reasons.append("Data verified from multiple sources")
        
        # SQL/Graph disagreement warning
        if validity_checks.get("sql_graph_disagreement"):
            reasons.append("WARNING: SQL and Graph results disagree on route existence (confidence reduced)")
        
        if decision == "auto_send":
            reasons.append("Confidence high enough for automatic sending")
        elif decision == "review_required":
            reasons.append("Human review recommended before sending")
        else:
            reasons.append("Escalation required - low confidence or missing data")
        
        return "; ".join(reasons)

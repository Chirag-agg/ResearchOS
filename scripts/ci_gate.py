import sys
import argparse

def evaluate_gates():
    """
    Evaluates BenchmarkRuns against Hard and Soft CI gates.
    """
    print("Evaluating CI Quality Gates...")
    
    # Mocks
    hard_gates = {
        "parser_crashes": 0,
        "offset_budget_exceeded": False,
        "determinism_score": 1.0,
        "golden_corpus_failures": 0
    }
    
    soft_gates = {
        "latency_degradation": 0.01, # 1% slower
        "recall_degradation": -0.001, # 0.1% worse
        "token_cost_increase": 0.02
    }
    
    failed_hard = False
    
    print("\n--- Hard Gates ---")
    if hard_gates["parser_crashes"] > 0:
        print("❌ FAILED: Parser crashed.")
        failed_hard = True
    if hard_gates["offset_budget_exceeded"]:
        print("❌ FAILED: Offset error budget exceeded.")
        failed_hard = True
    if hard_gates["determinism_score"] < 0.999:
        print("❌ FAILED: Pipeline determinism < 99.9%.")
        failed_hard = True
        
    print("\n--- Soft Gates ---")
    if soft_gates["latency_degradation"] > 0.03:
        print("⚠️ WARNING: Latency degraded > 3% beyond 2-sigma rolling mean.")
    if soft_gates["recall_degradation"] < -0.002:
        print("⚠️ WARNING: Recall degraded > 0.2%.")
        
    if failed_hard:
        print("\nBUILD FAILED.")
        sys.exit(1)
        
    print("\nBUILD PASSED.")
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enforces CI quality gates.")
    parser.parse_args()
    evaluate_gates()

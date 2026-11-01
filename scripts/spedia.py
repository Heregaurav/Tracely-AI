import argparse,json
from src.data.spedia import inspect_spedia,build_spedia

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Inspect authentic SPEDIA v2 and generate causal, leakage-audited features")
    parser.add_argument("command",choices=["inspect","features"])
    parser.add_argument("--source",default="logs_SPEDIA_annotated_en.csv")
    parser.add_argument("--output")
    parser.add_argument("--strategy",choices=["temporal","user_disjoint"],default="temporal")
    parser.add_argument("--common",action="store_true")
    args=parser.parse_args()
    result=inspect_spedia(args.source,args.output or "data/spedia/analysis") if args.command=="inspect" else build_spedia(args.source,args.output or "data/spedia/features",strategy=args.strategy,common=args.common)
    print(json.dumps(result,indent=2))

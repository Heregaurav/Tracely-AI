import argparse,json
from src.models.behavioral import train_spedia
if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Train and evaluate frozen, leakage-audited SPEDIA user-hour models")
    parser.add_argument("features")
    parser.add_argument("--artifacts",default="data/artifacts")
    parser.add_argument("--estimators",type=int,default=200)
    parser.add_argument("--epochs",type=int,default=100)
    parser.add_argument("--no-neural",action="store_true")
    args=parser.parse_args()
    report=train_spedia(args.features,args.artifacts,estimators=args.estimators,epochs=args.epochs,neural=not args.no_neural)
    print(json.dumps({"version":report["version"],"active_configuration":report["active_configuration"],"scope":report["evaluation_scope"],"held_out_metrics":report["held_out_metrics"]},indent=2))

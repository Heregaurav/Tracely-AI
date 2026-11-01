"""Run a new immutable development experiment without scoring the original test."""
import argparse
import json
from src.evaluation.spedia_experiment import run_experiment

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default='logs_SPEDIA_annotated_en.csv')
    p.add_argument('--frozen',default='data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223')
    p.add_argument('--output',required=True);p.add_argument('--epochs',type=int,default=100)
    a=p.parse_args();r=run_experiment(a.source,a.frozen,a.output,epochs=a.epochs)
    print(json.dumps({'selected':r['selected'],'scope':r['scope'],'final_test_status':r['final_test_status']},indent=2))

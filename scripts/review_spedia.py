"""python -m scripts.review_spedia --output data/spedia/review-v1"""
import argparse
from src.evaluation.spedia_review import review
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',default='data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223');p.add_argument('--features',default='data/spedia/features-temporal/features.parquet');p.add_argument('--source',default='logs_SPEDIA_annotated_en.csv');p.add_argument('--output',required=True);a=p.parse_args()
    result=review(a.run,a.features,a.source,a.output)
    print(result['original_operating_point']);print(result['validation_selected_operating_points'])

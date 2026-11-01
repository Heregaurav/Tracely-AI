"""Print a development-account mapping; read its password without shell arguments."""
import argparse
import getpass
import json
from werkzeug.security import generate_password_hash

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("role",choices=["VIEWER","ANALYST","ADMIN"])
    args=parser.parse_args()
    password=getpass.getpass("Development password (at least 12 characters): ")
    if len(password)<12:
        parser.error("Use at least 12 characters")
    print(json.dumps({args.username:{"role":args.role,"password_hash":generate_password_hash(password)}}))

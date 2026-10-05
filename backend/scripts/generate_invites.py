"""Generate one-time-style invite codes for BETA_INVITE_CODES."""
import secrets
import sys

count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
codes = ["ICE800-" + secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:10].upper() for _ in range(count)]
print("BETA_INVITE_CODES=" + ",".join(codes))
for i, code in enumerate(codes, 1):
    print(f"{i:02d}. {code}")

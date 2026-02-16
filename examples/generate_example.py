"""Generate an example .pfm file to see what the format looks like."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pfm.document import PFMDocument

doc = PFMDocument.create(
    agent="claude-code",
    model="claude-opus-4-6",
    tags="example,demo",
    version="1.0",
)

doc.add_section("content", """# Analysis Report

The codebase follows a clean MVC architecture with the following key findings:

1. Authentication is handled via JWT tokens with 24h expiry
2. Database queries use parameterized statements (no SQL injection risk)
3. Rate limiting is configured at 100 req/min per API key
4. CORS is properly restricted to known origins

Recommendation: Add request signing for webhook endpoints.""")

doc.add_section("chain", """User: Analyze this codebase for security issues and architecture patterns.

Agent: I'll examine the project structure, authentication flow, database layer,
and API configuration.

[Searched: auth/*.py, db/*.py, api/middleware.py]
[Read: 12 files, 3,400 lines]
[Tools: grep for SQL queries, checked CORS headers, traced auth flow]""")

doc.add_section("tools", """grep(pattern="SELECT|INSERT|UPDATE|DELETE", path="db/")
read_file("api/middleware.py")
read_file("auth/jwt_handler.py")
read_file("config/cors.py")
grep(pattern="rate_limit", path="api/")""")

doc.add_section("metrics", """tokens_in: 12450
tokens_out: 3200
latency_ms: 8934
model_cost_usd: 0.0847
files_read: 12
lines_analyzed: 3400""")

# Write the example
output = str(__import__("pathlib").Path(__file__).parent / "hello.pfm")
nbytes = doc.write(output)
print(f"Generated {output} ({nbytes} bytes)")

# Also print the raw content so you can see the format
print()
print("=" * 60)
print("RAW .pfm FILE CONTENTS:")
print("=" * 60)
print()
print(doc.to_bytes().decode("utf-8"))

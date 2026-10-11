"""Quick CLI: barcode in, score + explanation out. No server needed.

Usage: python demo.py [barcode]   (default: Nutella, for obvious reasons)
"""

import sys

from alternatives import find_alternatives
from explain import explain
from off_client import lookup
from risks import find_risks
from score import score_product


def main() -> None:
    barcode = sys.argv[1] if len(sys.argv) > 1 else "3017620422003"
    print(f"looking up {barcode} ...")
    product = lookup(barcode)
    if product is None:
        print("not found — try 3017620422003 (Nutella) or 4000417675217 (Ritter Sport)")
        return

    risks = find_risks(product)
    result = score_product(product, risks)
    text, explainer = explain(product, result, risks)

    brands = ", ".join(product["brands"]) or "unknown brand"
    score = result["score"] if result["score"] is not None else "?"
    print(f"\n{product['name']} — {brands}")
    print(f"score: {score}/100 ({result['band']})")
    print("\nfactors:")
    for f in result["factors"]:
        print(f"  {f['points']:+6.1f}  {f['label']}: {f['detail']}")
    if risks:
        print("\nrisky ingredients:")
        for r in risks:
            print(f"  [{r['level']}] {r['name']}: {r['reason']}")
    print(f"\nwhy [{explainer}]:\n{text}")

    alts = find_alternatives(product, result["score"])
    if alts["alternatives"]:
        print(f"\nhealthier picks in '{alts['category']}':")
        for a in alts["alternatives"]:
            print(f"  {a['score']:>3}  {a['name']} ({', '.join(a['brands'])}) [{a['barcode']}]")


if __name__ == "__main__":
    main()

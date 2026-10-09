"""Quick CLI: barcode in, score + explanation out. No server needed.

Usage: python demo.py [barcode]   (default: Nutella, for obvious reasons)
"""

import sys

from off_client import lookup
from score import score_product
from explain import default_explainer


def main() -> None:
    barcode = sys.argv[1] if len(sys.argv) > 1 else "3017620422003"
    print(f"looking up {barcode} ...")
    product = lookup(barcode)
    if product is None:
        print("not found — try 3017620422003 (Nutella) or 4000417675217 (Ritter Sport)")
        return

    result = score_product(product["nutriments"], product["nova_group"],
                           product["additives"])
    explainer = default_explainer()

    brands = ", ".join(product["brands"]) or "unknown brand"
    print(f"\n{product['name']} — {brands}")
    print(f"score: {result['score']}/100 ({result['band']})")
    print("\nfactors:")
    for f in result["factors"]:
        print(f"  {f['points']:+6.1f}  {f['label']}: {f['detail']}")
    print(f"\nwhy [{type(explainer).__name__}]:\n{explainer.explain(product, result)}")


if __name__ == "__main__":
    main()

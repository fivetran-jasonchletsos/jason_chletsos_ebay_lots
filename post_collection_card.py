#!/usr/bin/env python3
"""Post a personal collection duplicate card to eBay and mark it in ebay_status.json."""
import argparse, json, os, subprocess, sys, tempfile

PLAYER_PREFIX = {
    'dart':     'dart',
    'skattebo': 'skat',
    'nabers':   'nabe',
    'carter':   'cart',
}

STATUS_PATH = 'docs/collection/ebay_status.json'


def main():
    ap = argparse.ArgumentParser(description='List a collection duplicate on eBay')
    ap.add_argument('--player', required=True, choices=list(PLAYER_PREFIX))
    ap.add_argument('--id',     required=True, type=int)
    ap.add_argument('--image',  required=True)
    ap.add_argument('--title',  required=True)
    ap.add_argument('--price',  required=True, type=float)
    ap.add_argument('--apply',  action='store_true', help='Actually post (omit for dry run)')
    args = ap.parse_args()

    print(f"Player : {args.player} card #{args.id}")
    print(f"Image  : {args.image}")
    print(f"Title  : {args.title}")
    print(f"Price  : ${args.price:.2f}")

    if not os.path.exists(args.image):
        print(f"ERROR: image not found: {args.image}")
        sys.exit(1)

    if not args.apply:
        print("\nDry run — add --apply to post to eBay")
        return

    # Build a single-card batch JSON and hand off to post_from_scan.py
    batch = [{"image": args.image, "title": args.title, "price": args.price}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(batch, f)
        tmp = f.name

    try:
        result = subprocess.run(
            ['python3', 'post_from_scan.py', '--batch', tmp, '--apply'],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            sys.exit(1)

        # Try to extract eBay item ID from output
        item_id = None
        for line in result.stdout.split('\n'):
            for tok in line.split():
                if tok.isdigit() and len(tok) >= 10:
                    item_id = tok
                    break

        # Update ebay_status.json
        status = {}
        if os.path.exists(STATUS_PATH):
            with open(STATUS_PATH) as f:
                status = json.load(f)

        key = f"{args.player}_{args.id}"
        status[key] = item_id if item_id else True
        with open(STATUS_PATH, 'w') as f:
            json.dump(status, f, indent=2)
        print(f"\nMarked {key} as listed in {STATUS_PATH}")

        # Commit and push so the badge appears on the site
        subprocess.run(['git', 'add', STATUS_PATH], check=True)
        subprocess.run(['git', 'commit', '-m',
            f'Mark collection {args.player} #{args.id} listed on eBay'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("Pushed — ON EBAY badge will appear on collection site within ~30s")

    finally:
        os.unlink(tmp)


if __name__ == '__main__':
    main()

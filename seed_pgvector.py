#!/usr/bin/env python3
"""Build image embeddings with Gemini; cached calls resume interrupted runs."""
import argparse
import json
import vector_service as service


def main():
    parser = argparse.ArgumentParser(description='Index cat memes: keyword metadata + actual image embeddings')
    parser.add_argument('--api-key', help='Prefer GEMINI_API_KEY in .env instead')
    parser.add_argument('--no-vision', action='store_true', help='Compatibility flag; existing descriptions are always reused')
    args = parser.parse_args()
    print(f'Model: {service.DEFAULT_MODEL} | {service.DIMENSIONS} dimensions | image embeddings', flush=True)
    try:
        result = service.seed_database(api_key=args.api_key,
            progress=lambda n, total, name: print(f'[{n}/{total}] {name}', flush=True))
    except (service.EmbeddingError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vector_service as s
from google import genai
import os
with genai.Client(api_key=os.environ['GEMINI_API_KEY']) as client:
    for model in client.models.list():
        if 'embedding' in model.name or ('flash' in model.name and 'generateContent' in (model.supported_actions or [])):
            print(model.name, flush=True)
    if '--probe-quota' in sys.argv:
        from google.genai import types
        try:
            result = client.models.embed_content(model=s.DEFAULT_MODEL, contents='quota check',
                config=types.EmbedContentConfig(output_dimensionality=768),
                )
            print('Embedding probe: success')
        except Exception as exc:
            message = str(getattr(exc, 'message', '')).replace(os.environ['GEMINI_API_KEY'], '[redacted]')
            print('Embedding code:', getattr(exc,'code',None), message[:1500])

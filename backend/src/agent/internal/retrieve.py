from dotenv import load_dotenv
import functools
import os
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
import aiohttp
import numpy as np
import tritonclient.grpc as grpcclient
from pinecone import Pinecone, ServerlessSpec

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

EMBEDDING_URL = os.getenv("EMBEDDING_URL", "192.168.100.40:8001")
VSS_RETRIEVE_URL = os.getenv("VSS_RETRIEVE_URL", "http://192.168.100.40:9123/search")
PINECONE_NAMESPACE = "retrieval-bench-channel-1"
SEARCH_TOP_K = 10
CHANNEL_ID = "1"


@functools.cache
def get_triton_client(url: str):
    """Get Triton client with caching"""

    triton_client = grpcclient.InferenceServerClient(url=url, verbose=False)
    return triton_client


class Channel:
    """Embedding channel implementation for inference"""

    default_embed_url = EMBEDDING_URL
    default_embed_model = "embedding"

    @classmethod
    def is_available(cls) -> bool:
        return cls.is_embed_available()

    @classmethod
    def is_embed_available(cls) -> bool:
        try:
            triton_client = get_triton_client(url=cls.default_embed_url)

            # Health
            if not triton_client.is_server_live():
                return False

            if not triton_client.is_server_ready():
                return False

            if not triton_client.is_model_ready(cls.default_embed_model):
                return False
        except Exception as e:
            logger.error(f"Error checking embedding availability: {str(e)}")
            return False

        return True

    @classmethod
    def embed(
        cls,
        input: list[str],
        model_name: Optional[str] = None,
        model_version: Optional[str] = "",
        triton_url: str = None,
        batch_size: int = 128,
        *args,
        **kwargs,
    ) -> Union[Dict[str, Any], List[float], List[List[float]]]:
        try:
            import tritonclient.grpc as grpcclient

            model_name = model_name or cls.default_embed_model
            triton_url = triton_url or cls.default_embed_url

            triton_client = get_triton_client(url=triton_url)

            input_name = "INPUT"
            output_name = "OUTPUT"

            embeddings = []
            version = None
            for bi in range(0, len(input), batch_size):
                batch_inputs = input[bi : bi + batch_size]

                triton_inputs = [
                    grpcclient.InferInput(input_name, [len(batch_inputs), 1], "BYTES")
                ]
                input_array = np.array(
                    [str(text).encode("UTF-8") for text in batch_inputs]
                )
                input_array = np.expand_dims(input_array, axis=1)
                triton_inputs[0].set_data_from_numpy(input_array)

                outputs = [grpcclient.InferRequestedOutput(output_name)]

                infer_result = triton_client.infer(
                    model_name=model_name,
                    model_version=model_version,
                    inputs=triton_inputs,
                    outputs=outputs,
                )
                response = infer_result.get_response()
                batch_embeddings = infer_result.as_numpy(output_name).tolist()
                cur_version = response.model_version

                embeddings.extend(batch_embeddings)
                if version is None:
                    version = cur_version
                elif version != cur_version:
                    raise RuntimeError(
                        "Model version changed during embedding generation."
                    )

            return {"embeddings": embeddings, "model_version": version, "metadata": {}}

        except ImportError:
            logger.warning(
                "WARNING: tritonclient module not found. Using dummy embeddings."
            )
            # Generate dummy embeddings for testing without Triton server
            dummy_embeddings = [
                list(np.random.rand(1536).astype(float)) for _ in range(len(input))
            ]
            return {
                "embeddings": dummy_embeddings,
                "model_version": "dummy",
                "metadata": {},
            }
        except Exception as e:
            logger.error(f"Error generating embeddings: {str(e)}")
            raise


async def generate_embeddings(texts: List[str]) -> Tuple[List[List[float]], float]:
    """Generate embeddings using the Channel class"""
    logger.debug(f"Generating embeddings for {len(texts)} texts")
    # Use the inline Channel implementation
    start_time = time.time()
    result = Channel.embed(input=texts)
    end_time = time.time()
    latency = end_time - start_time
    logger.debug(
        f"Generated {len(result['embeddings'])} embeddings with dimension {len(result['embeddings'][0]) if result['embeddings'] else 0} in {latency:.2f} seconds"
    )
    return result["embeddings"], latency


async def query_to_vss(vector: List[float], text: str, top_k: int = 5):
    payload = json.dumps(
        {
            "db_provider": "pinecone",
            "namespace": PINECONE_NAMESPACE,
            "channel_id": CHANNEL_ID,
            "model_version": "240718",
            "type": "chunk",
            "vector": vector,
            "text": text,
            "top_k": top_k,
            "lang": "ko",
        }
    )
    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", VSS_RETRIEVE_URL, headers=headers, data=payload)

    return response.json()


if __name__ == "__main__":
    import asyncio

    async def main():
        query = "airCloset Dressにおいて、お客様が起因で汚損・紛失があった場合の対応について、暫定対応も含め教えて下さい"
        embeddings, latency = await generate_embeddings([query])
        # print(f"Latency: {latency:.2f} seconds")
        print(f"First embedding: {embeddings[0] if embeddings else []}")

        # results = await query_to_vss(embeddings[0], query)
        # print(results)

    asyncio.run(main())

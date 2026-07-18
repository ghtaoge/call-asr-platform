from __future__ import annotations

import argparse
import asyncio

import grpc

from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc


async def check(port: int) -> int:
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        response = await asr_pb2_grpc.AsrServiceStub(channel).Check(
            asr_pb2.HealthRequest(), timeout=5
        )
        return 0 if response.status == "SERVING" else 1
    except Exception:
        return 1
    finally:
        await channel.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    raise SystemExit(asyncio.run(check(parser.parse_args().port)))


if __name__ == "__main__":
    main()

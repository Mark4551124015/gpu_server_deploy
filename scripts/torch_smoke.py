"""Run with torchrun on both nodes; verify NCCL all_reduce and a DDP train step."""
from datetime import timedelta
import os
import socket
import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel

local_rank = int(os.environ["LOCAL_RANK"])
torch.cuda.set_device(local_rank)
dist.init_process_group("nccl", timeout=timedelta(seconds=120))
try:
    rank, world = dist.get_rank(), dist.get_world_size()
    value = torch.tensor([rank + 1.0], device=f"cuda:{local_rank}")
    dist.all_reduce(value)
    expected = world * (world + 1) / 2
    assert value.item() == expected, (value.item(), expected)
    torch.manual_seed(1)
    model = DistributedDataParallel(torch.nn.Linear(4, 2).cuda(), device_ids=[local_rank])
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    model(torch.ones(8, 4, device="cuda") * (rank + 1)).square().mean().backward()
    optimizer.step()
    weight = model.module.weight.detach()
    weights = [torch.empty_like(weight) for _ in range(world)]
    dist.all_gather(weights, weight)
    assert all(torch.equal(weight, item) for item in weights), "DDP weights diverged"
    dist.barrier()
    print(f"PASS host={socket.gethostname()} rank={rank}/{world} GPU={local_rank} all_reduce={value.item()} DDP=OK", flush=True)
finally:
    dist.destroy_process_group()

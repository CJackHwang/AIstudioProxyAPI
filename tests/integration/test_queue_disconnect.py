"""
Integration tests for queue disconnect detection and handling.

These tests verify that client disconnect detection works correctly with REAL
asyncio.Queue, catching edge cases that mocked tests miss.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api_utils.queue_worker import QueueManager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_queue_disconnects_real_queue(real_server_state, mock_http_request):
    """
    Verify that check_queue_disconnects correctly identifies disconnected clients
    using a REAL asyncio.Queue.

    This tests the actual queue get/put behavior, not mocked calls.
    """
    queue_manager = QueueManager()
    queue_manager.request_queue = real_server_state.request_queue
    queue_manager.logger = real_server_state.logger

    # Create three items with different disconnect states
    disconnected_req = MagicMock()
    disconnected_req.is_disconnected = AsyncMock(return_value=True)

    connected_req = MagicMock()
    connected_req.is_disconnected = AsyncMock(return_value=False)

    error_req = MagicMock()
    error_req.is_disconnected = AsyncMock(side_effect=Exception("Check failed"))

    items = [
        {
            "req_id": "disconnected",
            "http_request": disconnected_req,
            "cancelled": False,
            "result_future": asyncio.Future(),
        },
        {
            "req_id": "connected",
            "http_request": connected_req,
            "cancelled": False,
            "result_future": asyncio.Future(),
        },
        {
            "req_id": "error",
            "http_request": error_req,
            "cancelled": False,
            "result_future": asyncio.Future(),
        },
    ]

    # Add items to REAL queue
    for item in items:
        await real_server_state.request_queue.put(item)

    # Run check_queue_disconnects
    await queue_manager.check_queue_disconnects()

    # Verify queue state: all items should be requeued
    assert real_server_state.request_queue.qsize() == 3

    # Extract items from queue to verify their states
    requeued_items = []
    while not real_server_state.request_queue.empty():
        item = await real_server_state.request_queue.get()
        requeued_items.append(item)

    # Find each item by req_id
    disconnected_item = next(i for i in requeued_items if i["req_id"] == "disconnected")
    connected_item = next(i for i in requeued_items if i["req_id"] == "connected")
    error_item = next(i for i in requeued_items if i["req_id"] == "error")

    # Verify disconnected item was marked cancelled and future set
    assert disconnected_item["cancelled"] is True
    assert disconnected_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        disconnected_item["result_future"].result()
    assert exc.value.status_code == 499

    # Verify connected item unchanged
    assert connected_item["cancelled"] is False
    assert not connected_item["result_future"].done()

    # Verify error item was requeued but not marked cancelled (exception caught)
    assert not error_item["result_future"].done()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_fifo_order_maintained(real_server_state):
    """
    Verify that queue maintains FIFO order with real asyncio.Queue.

    This ensures request processing order is predictable.
    """
    queue = real_server_state.request_queue

    # Add items with specific order
    for i in range(10):
        await queue.put({"id": i, "timestamp": asyncio.get_event_loop().time()})

    # Extract items and verify order
    extracted = []
    while not queue.empty():
        item = await queue.get()
        extracted.append(item["id"])

    assert extracted == list(range(10)), "Queue did not maintain FIFO order"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_task_done_tracking(real_server_state):
    """
    Verify that queue.task_done() works correctly with queue.join().

    This is important for graceful shutdown and ensuring all requests are processed.
    """
    queue = real_server_state.request_queue

    # Add items
    num_items = 5
    for i in range(num_items):
        await queue.put({"id": i})

    async def worker():
        """Process all items and mark done."""
        processed = []
        for _ in range(num_items):
            item = await queue.get()
            processed.append(item["id"])
            await asyncio.sleep(0.01)  # Simulate processing
            queue.task_done()
        return processed

    # Start worker and wait for all tasks to complete
    worker_task = asyncio.create_task(worker())

    # Wait for queue to be fully processed
    await asyncio.wait_for(queue.join(), timeout=2.0)

    # Verify all items were processed
    processed = await worker_task
    assert len(processed) == num_items
    assert queue.empty()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_disconnect_during_processing(real_server_state):
    """
    Verify that disconnect detection works even while items are being processed.

    This simulates the race condition where a client disconnects after their
    request is queued but before it starts processing.
    """
    queue_manager = QueueManager()
    queue_manager.request_queue = real_server_state.request_queue
    queue_manager.logger = real_server_state.logger
    queue_manager.processing_lock = real_server_state.processing_lock

    # Create item that will disconnect during check
    req = MagicMock()
    req.is_disconnected = AsyncMock(return_value=False)  # Initially connected

    item = {
        "req_id": "test",
        "http_request": req,
        "cancelled": False,
        "result_future": asyncio.Future(),
    }

    await real_server_state.request_queue.put(item)

    # Simulate disconnect happening between check_queue_disconnects and processing
    async def delayed_disconnect():
        await asyncio.sleep(0.05)
        req.is_disconnected = AsyncMock(return_value=True)

    disconnect_task = asyncio.create_task(delayed_disconnect())

    # First check - should find it connected
    await queue_manager.check_queue_disconnects()

    # Wait for disconnect to happen
    await disconnect_task

    # Second check - should now find it disconnected
    await queue_manager.check_queue_disconnects()

    # Extract item
    checked_item = await real_server_state.request_queue.get()

    # Verify it was marked as cancelled
    assert checked_item["cancelled"] is True
    assert checked_item["result_future"].done()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_multiple_disconnects_batch(real_server_state):
    """
    Verify that check_queue_disconnects handles multiple disconnected clients
    correctly in a single check.

    This tests batch processing efficiency.
    """
    queue_manager = QueueManager()
    queue_manager.request_queue = real_server_state.request_queue
    queue_manager.logger = real_server_state.logger

    # Create 10 items, half disconnected
    items = []
    for i in range(10):
        is_disconnected = i % 2 == 0  # Even numbered are disconnected
        req = MagicMock()
        req.is_disconnected = AsyncMock(return_value=is_disconnected)

        item = {
            "req_id": f"req-{i}",
            "http_request": req,
            "cancelled": False,
            "result_future": asyncio.Future(),
        }
        items.append(item)
        await real_server_state.request_queue.put(item)

    # Run check
    await queue_manager.check_queue_disconnects()

    # Extract and verify
    requeued = []
    while not real_server_state.request_queue.empty():
        requeued.append(await real_server_state.request_queue.get())

    # Count cancelled items
    cancelled_count = sum(1 for item in requeued if item["cancelled"])
    assert cancelled_count == 5  # Half should be cancelled

    # Verify all disconnected items have futures set
    for item in requeued:
        if item["cancelled"]:
            assert item["result_future"].done()
            with pytest.raises(HTTPException) as exc:
                item["result_future"].result()
            assert exc.value.status_code == 499


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_next_request_timeout_real_queue(real_server_state):
    """
    Verify that get_next_request properly times out with empty REAL queue.

    This tests actual asyncio.wait_for behavior, not mocked timeouts.
    """
    from unittest.mock import patch

    queue_manager = QueueManager()
    queue_manager.request_queue = real_server_state.request_queue
    queue_manager.logger = real_server_state.logger

    # Queue is empty, should timeout - use short timeout for fast testing
    # Create a replacement wait_for that uses short timeout
    original_wait_for = asyncio.wait_for

    async def short_timeout_wait_for(coro, timeout):
        # Use 0.1s timeout instead of 5s for faster test
        return await original_wait_for(coro, timeout=0.1)

    with patch(
        "api_utils.queue_worker.asyncio.wait_for", side_effect=short_timeout_wait_for
    ):
        start_time = asyncio.get_event_loop().time()
        result = await queue_manager.get_next_request()
        elapsed = asyncio.get_event_loop().time() - start_time

    assert result is None
    # Should timeout after ~0.1 seconds with patched timeout
    assert elapsed < 0.5  # Allow margin for async overhead


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_next_request_returns_item_real_queue(real_server_state):
    """
    Verify that get_next_request returns item from REAL queue.
    """
    queue_manager = QueueManager()
    queue_manager.request_queue = real_server_state.request_queue
    queue_manager.logger = real_server_state.logger

    # Add item
    expected_item = {"req_id": "test", "data": "test_data"}
    await real_server_state.request_queue.put(expected_item)

    # Get item
    result = await queue_manager.get_next_request()

    assert result == expected_item
    assert real_server_state.request_queue.empty()

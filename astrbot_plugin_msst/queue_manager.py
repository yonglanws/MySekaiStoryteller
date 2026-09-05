import asyncio
import time
import uuid
from enum import Enum
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from astrbot.api import logger


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class QueueTask:
    """队列任务数据类"""
    task_id: str
    user_id: str
    priority: int
    created_at: float
    coroutine_func: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 600
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class VideoExportQueue:
    """视频导出队列管理器（高并发优化版）"""

    def __init__(self, max_concurrent: int = 2, max_queue_size: int = 30,
                 default_timeout: int = 600, default_max_retries: int = 1,
                 cleanup_interval: int = 180):
        self._queue: list[QueueTask] = []
        self._running_tasks: dict[str, QueueTask] = {}
        self._completed_tasks: dict[str, QueueTask] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._max_queue_size = max_queue_size
        self._default_timeout = default_timeout
        self._default_max_retries = default_max_retries
        self._task_events: dict[str, asyncio.Event] = {}
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        self._processor_task: Optional[asyncio.Task] = None
        self._running = False
        self._stats = {
            "total_enqueued": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0
        }
        # 高并发优化：用户任务聚合，同一用户的多个任务合并处理
        self._user_task_groups: dict[str, list[str]] = {}

    async def start(self):
        """启动队列处理器和清理任务"""
        if self._running:
            return
        self._running = True
        self._processor_task = asyncio.create_task(self.process_queue())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"视频导出队列已启动（并发={self._max_concurrent}, 容量={self._max_queue_size}）")

    async def stop(self):
        """停止队列处理器"""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("视频导出队列已停止")

    async def add_task(self, user_id: str, coroutine_func: Callable,
                       priority: int = 0, args: tuple = (), kwargs: dict = None,
                       timeout_seconds: int = None, max_retries: int = None) -> str:
        """添加任务到队列（优化版：支持用户任务聚合）"""
        async with self._lock:
            if len(self._queue) + len(self._running_tasks) >= self._max_queue_size:
                raise QueueFullError(
                    f"队列已满（{self._max_queue_size}），请稍后重试"
                )

            task_id = str(uuid.uuid4())
            timeout = timeout_seconds or self._default_timeout
            retries = max_retries if max_retries is not None else self._default_max_retries

            task = QueueTask(
                task_id=task_id,
                user_id=user_id,
                priority=priority,
                created_at=time.time(),
                coroutine_func=coroutine_func,
                args=args,
                kwargs=kwargs or {},
                timeout_seconds=timeout,
                max_retries=retries
            )

            # 高并发优化：检查同一用户是否已有pending任务，进行智能排序
            user_pending_count = sum(1 for t in self._queue if t.user_id == user_id and t.status == TaskStatus.PENDING)
            
            # 如果同一用户已有多个pending任务，降低优先级避免垄断
            adjusted_priority = priority + min(user_pending_count * 2, 10)
            task.priority = adjusted_priority

            self._queue.append(task)
            
            # 优化排序：优先级 > 创建时间 > 用户公平性
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            
            # 记录用户任务组
            if user_id not in self._user_task_groups:
                self._user_task_groups[user_id] = []
            self._user_task_groups[user_id].append(task_id)
            
            self._task_events[task_id] = asyncio.Event()
            self._stats["total_enqueued"] += 1

            logger.info(f"任务已加入队列: {task_id[:8]}, 用户={user_id}, "
                        f"队列长度={len(self._queue)}, 优先级={adjusted_priority}(原{priority}), "
                        f"用户pending={user_pending_count}")

            return task_id

    async def get_task_status(self, task_id: str) -> Optional[dict]:
        """获取任务状态"""
        async with self._lock:
            task = self._find_task(task_id)
            if not task:
                return None

            position = None
            if task.status == TaskStatus.PENDING:
                # 计算前面有多少个任务：正在运行的任务 + 队列中排在前面的pending任务
                running_count = len(self._running_tasks)
                pending_before = sum(1 for t in self._queue
                                     if t.created_at < task.created_at and t.status == TaskStatus.PENDING)
                position = running_count + pending_before

            return {
                "task_id": task_id,
                "status": task.status.value,
                "user_id": task.user_id,
                "position": position,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "retry_count": task.retry_count,
                "error": task.error,
                "result": task.result
            }

    async def wait_for_task(self, task_id: str, timeout: float = None) -> Optional[dict]:
        """等待任务完成"""
        if task_id not in self._task_events:
            return None

        try:
            await asyncio.wait_for(
                self._task_events[task_id].wait(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return {"status": "timeout", "message": "等待任务超时"}

        return await self.get_task_status(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        async with self._lock:
            task = self._find_task(task_id)
            if not task:
                return False

            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                self._queue.remove(task)
                if task_id in self._task_events:
                    self._task_events[task_id].set()
                self._stats["total_cancelled"] += 1
                logger.info(f"任务已取消: {task_id[:8]}")
                return True
            elif task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.CANCELLED
                if task_id in self._task_events:
                    self._task_events[task_id].set()
                self._stats["total_cancelled"] += 1
                logger.info(f"运行中任务已标记取消: {task_id[:8]}")
                return True

            return False

    async def get_queue_stats(self) -> dict:
        """获取队列统计信息"""
        async with self._lock:
            pending = [t for t in self._queue if t.status == TaskStatus.PENDING]
            running = len(self._running_tasks)
            completed = len([t for t in self._completed_tasks.values()
                             if t.status == TaskStatus.COMPLETED])
            failed = len([t for t in self._completed_tasks.values()
                          if t.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)])

            return {
                "pending_count": len(pending),
                "running_count": running,
                "completed_count": completed,
                "failed_count": failed,
                "total_processed": len(self._completed_tasks),
                "total_enqueued": self._stats["total_enqueued"],
                "total_completed": self._stats["total_completed"],
                "total_failed": self._stats["total_failed"],
                "total_cancelled": self._stats["total_cancelled"],
                "max_concurrent": self._max_concurrent,
                "queue_size_limit": self._max_queue_size
            }

    async def estimate_wait_time(self, task_id: str) -> int:
        """预估任务等待时间（秒）"""
        async with self._lock:
            task = self._find_task(task_id)
            if not task:
                return 0

            if task.status != TaskStatus.PENDING:
                return 0

            position = sum(1 for t in self._queue
                          if t.created_at < task.created_at and t.status == TaskStatus.PENDING)

            if position == 0:
                return 0

            completed_tasks = [t for t in self._completed_tasks.values()
                              if t.status == TaskStatus.COMPLETED 
                              and t.started_at and t.completed_at]

            if completed_tasks:
                recent_tasks = completed_tasks[-5:]
                avg_duration = sum(t.completed_at - t.started_at for t in recent_tasks) / len(recent_tasks)
            else:
                avg_duration = 60

            estimated_seconds = int(position * avg_duration)

            running_count = len(self._running_tasks)
            if running_count > 0:
                estimated_seconds = int(estimated_seconds / (running_count + 1))

            return max(estimated_seconds, position * 10)

    async def process_queue(self):
        """处理队列中的任务（高并发优化版：批量处理+智能调度）"""
        while self._running:
            try:
                async with self._lock:
                    available_slots = self._max_concurrent - len(self._running_tasks)
                    if available_slots <= 0:
                        await asyncio.sleep(0.05)
                        continue

                    tasks_to_start = []
                    processed_users = set()

                    for task in self._queue:
                        if task.status != TaskStatus.PENDING:
                            continue

                        if len(tasks_to_start) >= available_slots:
                            break

                        if task.user_id in processed_users:
                            continue

                        processed_users.add(task.user_id)
                        task.status = TaskStatus.RUNNING
                        task.started_at = time.time()
                        self._running_tasks[task.task_id] = task
                        tasks_to_start.append(task)

                    self._queue = [t for t in self._queue
                                  if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

                if tasks_to_start:
                    for task in tasks_to_start:
                        asyncio.create_task(self._execute_with_semaphore(task))
                    logger.info(f"批量启动 {len(tasks_to_start)} 个任务，当前运行: {len(self._running_tasks)}")

                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"队列处理异常: {e}")
                await asyncio.sleep(1)

    async def _execute_with_semaphore(self, task: QueueTask):
        """使用信号量执行任务"""
        async with self._semaphore:
            await self._execute_task(task)

    async def _execute_task(self, task: QueueTask):
        """执行单个任务"""
        try:
            coro = task.coroutine_func(*task.args, **task.kwargs)

            try:
                result = await asyncio.wait_for(coro, timeout=task.timeout_seconds)
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = time.time()
                self._stats["total_completed"] += 1

                logger.info(f"任务完成: {task.task_id[:8]}, "
                            f"耗时={int(task.completed_at - task.started_at)}秒")

            except asyncio.TimeoutError:
                task.status = TaskStatus.TIMEOUT
                task.error = f"任务超时（{task.timeout_seconds}秒）"
                task.completed_at = time.time()
                self._stats["total_failed"] += 1

                logger.warning(f"任务超时: {task.task_id[:8]}, "
                               f"用户={task.user_id}")

            except Exception as e:
                task.error = str(e)
                logger.error(f"任务执行失败: {task.task_id[:8]}, 错误={e}")

                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.started_at = None
                    task.error = None

                    async with self._lock:
                        self._queue.append(task)
                        self._queue.sort(key=lambda t: (t.priority, t.created_at))

                    logger.info(f"任务将重试: {task.task_id[:8]}, "
                                f"第{task.retry_count}次重试")
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    self._stats["total_failed"] += 1
                    logger.error(f"任务最终失败: {task.task_id[:8]}, "
                                 f"已重试{task.retry_count}次")

        finally:
            async with self._lock:
                if task.task_id in self._running_tasks:
                    del self._running_tasks[task.task_id]

                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                    self._completed_tasks[task.task_id] = task

                if task.task_id in self._task_events:
                    self._task_events[task.task_id].set()

    async def _cleanup_loop(self):
        """定期清理已完成的任务"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_completed_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理任务异常: {e}")

    async def _cleanup_completed_tasks(self, max_age_seconds: int = 1800):
        """清理已完成的任务记录（30分钟）"""
        async with self._lock:
            now = time.time()
            to_remove = []

            for task_id, task in self._completed_tasks.items():
                if task.completed_at and (now - task.completed_at) > max_age_seconds:
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self._completed_tasks[task_id]
                if task_id in self._task_events:
                    del self._task_events[task_id]

            if to_remove:
                logger.info(f"清理了 {len(to_remove)} 个已完成的任务记录")

    def _find_task(self, task_id: str) -> Optional[QueueTask]:
        """查找任务（需在锁内调用）"""
        for task in self._queue:
            if task.task_id == task_id:
                return task

        if task_id in self._running_tasks:
            return self._running_tasks[task_id]

        return self._completed_tasks.get(task_id)


class QueueFullError(Exception):
    """队列已满异常"""
    pass

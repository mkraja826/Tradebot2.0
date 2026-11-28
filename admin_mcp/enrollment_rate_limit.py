import threading
import time

class EnrollmentLimiter:
    """Bounded global token bucket; shared by threads in one worker."""
    def __init__(self, capacity=30, refill_per_second=0.5, clock=time.monotonic):
        self.capacity=capacity
        self.refill=refill_per_second
        self.clock=clock
        self.tokens=float(capacity)
        self.last=clock()
        self.lock=threading.Lock()

    def allow(self):
        with self.lock:
            now=self.clock()
            self.tokens=min(self.capacity,self.tokens+max(0,now-self.last)*self.refill)
            self.last=now
            if self.tokens<1:
                return False
            self.tokens-=1
            return True

class ModelUnavailable(Exception):
    def __init__(self, reason='unavailable'):
        self.reason = reason
        super().__init__(reason)

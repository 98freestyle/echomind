bind = "127.0.0.1:8000"     # Nginx will proxy to this
workers = 4                 # Match what you're using in systemd
threads = 2                 # 2 threads per worker = 8 concurrent jobs max
timeout = 600               # ⏱ Long enough for big files
graceful_timeout = 30       # Let workers shut down cleanly
keepalive = 2               # Keep connections alive briefly
loglevel = "info"           # Show clean logs
accesslog = "-"             # Optional: "-" = print to stdout
errorlog = "-"              # Optional: "-" = print to stderr

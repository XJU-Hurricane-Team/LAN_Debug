# 是否开启debug模式
debug = False
# 访问地址
bind = "0.0.0.0:8000"
# 工作进程数
workers = 1
# 工作线程数
threads = 4
# 超时时间
timeout = 600
# 输出日志级别
loglevel = 'warning'
# 存放日志路径
pidfile = "./log/gunicorn.pid"
# 存放日志路径
accesslog = "./log/access.log"
# 存放日志路径
errorlog = "./log/debug.log"
# RTT 和 J-Link 进程都依赖单进程内存状态，避免多 worker 让选中设备和 RTT 缓冲分裂
preload_app = False

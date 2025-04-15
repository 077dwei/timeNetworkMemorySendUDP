import tkinter as tk
import psutil
from datetime import datetime
import ctypes
import sys
from tkinter import messagebox, ttk, simpledialog
from typing import List
import winreg
import socket
import threading
import time
from tkinter import messagebox, scrolledtext  # 导入 scrolledtext 模块
import pystray
from PIL import Image
import os


class MemoryManager:
    """使用 bytearray 模拟内存管理的类"""

    def __init__(self):
        self.memory_pool: List[bytearray] = []  # 存储内存块
        self.memory_sizes: List[int] = []  # 存储每个内存块的大小
        self.total_size: int = 0  # 记录总分配的内存大小 (字节)

    def _bytes_to_mb(self, size_bytes: int) -> int:
        """将字节转换为 MB"""
        return size_bytes // (1024 * 1024)

    def add_memory(self, size_mb: int) -> str:
        """增加内存"""
        size_bytes = size_mb * 1024 * 1024
        memory_block = bytearray(size_bytes)
        self.memory_pool.append(memory_block)
        self.memory_sizes.append(size_bytes)
        self.total_size += size_bytes
        return f"成功分配 {size_bytes} 字节内存！ ({self._bytes_to_mb(size_bytes)} MB)"

    def reduce_memory(self, size_mb: int) -> str:
        """减少内存"""
        if not self.memory_pool:
            return "没有可释放的内存块！"
        size_bytes = size_mb * 1024 * 1024
        remaining_size = size_bytes
        while remaining_size > 0 and self.memory_pool:
            last_block_size = self.memory_sizes[-1]
            if last_block_size <= remaining_size:
                self.memory_pool.pop()
                self.memory_sizes.pop()
                self.total_size -= last_block_size
                remaining_size -= last_block_size
            else:
                new_size = last_block_size - remaining_size
                self.memory_pool[-1] = bytearray(new_size)
                self.memory_sizes[-1] = new_size
                self.total_size -= remaining_size
                remaining_size = 0
        reduced_size = size_bytes - remaining_size
        return f"成功减少 {reduced_size} 字节内存！ ({self._bytes_to_mb(reduced_size)} MB)"

    def reset_memory(self) -> str:
        """重置内存"""
        self.memory_pool.clear()
        self.memory_sizes.clear()
        self.total_size = 0
        return "内存已重置！"

    def get_memory_usage(self) -> str:
        """获取内存占用信息"""
        return (f"当前分配的内存块数量：{len(self.memory_pool)}\n"
                f"当前总分配的内存大小：\n{self.total_size} 字节 ({self._bytes_to_mb(self.total_size)} MB)")


class ClockWindow(tk.Tk):
    def __init__(self):
        super().__init__()

        # 阻止系统休眠
        self.sleep_prevented = True
        self.prevent_sleep()

        # 各悬浮窗口初始状态
        self.network_window = None
        self.memory_window = None
        self.ip_window = None
        self.packet_sender_window = None

        # 初始化内存管理器
        self.memory_manager = MemoryManager()

        # 主窗口属性设置
        self.geometry("85x30")
        self.attributes('-topmost', True)
        self.config(bg="black")
        self.overrideredirect(True)

        # 创建时间显示标签
        self.time_label = tk.Label(self, text="00:00:00",
                                   font=("Helvetica", 14), fg="yellow", bg="black")
        self.time_label.pack(expand=True)

        # 绑定拖动和右键菜单事件
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.on_motion)
        self.bind("<Button-3>", self.show_menu)

        # 创建系统托盘图标
        self.create_tray_icon()

        self.update_time()  # 每秒更新时间
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.position_near_mouse()  # 定位在鼠标附近

        # 数据包发送相关变量
        self.is_sending = False
        self.bytes_sent = 0
        self.start_time = 0
        self.lock = threading.Lock()

        # 网速刷新间隔（单位毫秒），默认700ms
        self.network_refresh_interval = 700

        # 启动定时器，定期检查并恢复“阻止系统休眠”状态
        self.after(5000, self.prevent_sleep_if_needed)

        self.mainloop()

        # ------------------- 主窗口及公共方法 -------------------
    def show_menu(self, event):
        """显示主窗口右键菜单"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="立即休眠", command=self.hibernate_system)
        if self.sleep_prevented:
            menu.add_command(label="允许休眠", command=self.set_allow_sleep)
        else:
            menu.add_command(label="阻止休眠", command=self.set_prevent_sleep)
        if self.network_window:
            menu.add_command(label="隐藏网速", command=self.close_network_window)
        else:
            menu.add_command(label="显示网速", command=self.open_network_window)
        if self.memory_window:
            menu.add_command(label="隐藏内存管理", command=self.close_memory_window)
        else:
            menu.add_command(label="显示内存管理", command=self.open_memory_window)
        if self.packet_sender_window:
            menu.add_command(label="隐藏数据包发送", command=self.close_packet_sender_window)
        else:
            menu.add_command(label="显示数据包发送", command=self.open_packet_sender_window)
        auto_start_label = "禁用开机自启动" if self.is_auto_start_enabled() else "启用开机自启动"
        menu.add_command(label=auto_start_label, command=self.toggle_auto_start)
        menu.add_command(label="隐藏所有窗口", command=self.hide_all_windows)  # 添加隐藏选项
        menu.add_command(label="关于此软件", command=self.show_about)
        menu.add_command(label="更新日志", command=self.show_changelog)
        menu.add_separator()
        menu.add_command(label="退出全部程序", command=self.on_closing)
        menu.post(event.x_root, event.y_root)

    # ------------------- 系统托盘图标相关方法 -------------------
    def create_tray_icon(self):
        """创建系统托盘图标"""
        icon_path = 'clock.png'
        if not os.path.exists(icon_path):
            image = Image.new('RGB', (64, 64), color='yellow')
        else:
            image = Image.open(icon_path)

        menu = pystray.Menu(
            pystray.MenuItem("显示", self.show_all_windows),
            pystray.MenuItem("退出", self.on_closing)
        )

        self.tray_icon = pystray.Icon("ClockWindow", image, "多功能数字时钟", menu)
        # self.tray_icon.on_click = lambda icon, query: self.show_all_windows(icon, query)
        # self.tray_icon.on_double_click = lambda icon, item: self.show_all_windows(icon, item)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_all_windows(self):
        print("show_all_windows called")  # 调试信息
        self.deiconify()
        if self.network_window:
            self.network_window.deiconify()
        if self.memory_window:
            self.memory_window.deiconify()
        if self.ip_window:
            self.ip_window.deiconify()
        if self.packet_sender_window:
            self.packet_sender_window.deiconify()

    def hide_all_windows(self):
        """隐藏所有窗口"""
        self.withdraw()  # 隐藏主窗口
        if self.network_window:
            self.network_window.withdraw()
        if self.memory_window:
            self.memory_window.withdraw()
        if self.ip_window:
            self.ip_window.withdraw()
        if self.packet_sender_window:
            self.packet_sender_window.withdraw()


    def on_closing(self):
        """退出程序时关闭所有窗口和托盘图标"""
        self.restore_sleep()
        if self.network_window:
            self.network_window.destroy()
        if self.memory_window:
            self.memory_window.destroy()
        if self.ip_window:
            self.ip_window.destroy()
        if self.packet_sender_window:
            self.close_packet_sender_window()
        self.memory_manager.reset_memory()
        self.tray_icon.stop()  # 停止托盘图标
        self.destroy()

    def position_near_mouse(self):
        """将主窗口定位到鼠标附近"""
        mouse_x = self.winfo_pointerx()
        mouse_y = self.winfo_pointery()
        window_width = 85
        window_height = 30
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        offset_x, offset_y = 10, 10
        pos_x = mouse_x + offset_x
        pos_y = mouse_y + offset_y
        if pos_x + window_width > screen_width:
            pos_x = screen_width - window_width - 5
        if pos_y + window_height > screen_height:
            pos_y = screen_height - window_height - 5
        if pos_x < 0: pos_x = 5
        if pos_y < 0: pos_y = 5
        self.geometry(f"+{pos_x}+{pos_y}")

    def prevent_sleep(self):
        """阻止系统休眠"""
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)

    def restore_sleep(self):
        """恢复系统休眠"""
        ES_CONTINUOUS = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

    def hibernate_system(self):
        """立即将系统置于休眠状态"""
        # 临时允许系统休眠，但不改变 self.sleep_prevented
        ES_CONTINUOUS = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        powrprof = ctypes.WinDLL("powrprof.dll")
        set_suspend_state = powrprof.SetSuspendState
        set_suspend_state.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        set_suspend_state.restype = ctypes.c_int
        result = set_suspend_state(1, 1, 0)
        if not result:
            error_code = ctypes.get_last_error()
            messagebox.showerror("错误", f"无法进入休眠状态，错误代码：{error_code}")

    def prevent_sleep_if_needed(self):
        """定期检查并恢复阻止系统休眠的状态"""
        if self.sleep_prevented:
            self.prevent_sleep()
        self.after(5000, self.prevent_sleep_if_needed)

    def start_move(self, event):
        """记录主窗口拖动起始位置"""
        self.x = event.x_root - self.winfo_x()
        self.y = event.y_root - self.winfo_y()

    def on_motion(self, event):
        """拖动主窗口"""
        x = event.x_root - self.x
        y = event.y_root - self.y
        self.geometry(f"+{x}+{y}")


    def set_prevent_sleep(self):
        """设置阻止系统休眠"""
        self.sleep_prevented = True
        self.prevent_sleep()

    def set_allow_sleep(self):
        """设置允许系统休眠"""
        self.sleep_prevented = False
        self.restore_sleep()

    def is_auto_start_enabled(self):
        """检查是否启用了开机自启动"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run")
            winreg.QueryValueEx(key, "ClockWindow")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False

    def set_auto_start(self, enable):
        """设置或取消开机自启动"""
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_WRITE)
        if enable:
            winreg.SetValueEx(key, "ClockWindow", 0, winreg.REG_SZ, sys.executable)
        else:
            try:
                winreg.DeleteValue(key, "ClockWindow")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)

    def toggle_auto_start(self):
        """切换开机自启动状态"""
        current_state = self.is_auto_start_enabled()
        self.set_auto_start(not current_state)
        messagebox.showinfo("提示", f"开机自启动已{'启用' if not current_state else '禁用'}")

    def show_about(self):
        """显示关于信息"""
        about_text = (
            "多功能数字时钟 V6.0\n"
            "作者：d770（由 d770本人 & Grok3(主) & ChatGPT4o 创作）\n"
            "功能：\n"
            "- 显示时间 & 可选网速显示 (时间每秒校对一次，网速可自定义刷新间隔)\n"
            "- 可选内存管理功能\n"
            "- 置顶 & 无边框设计\n"
            "- 拖动 & 右键菜单\n"
            "- 阻止/允许系统休眠 (默认阻止系统休眠)\n"
            "- 立即休眠系统\n"
            "- 向指定 IP 地址持续实时多线程发送UDP数据包（MB/GB，可设置发送频率）\n"
            "- 网速、内存管理及数据包发送功能可独立开关\n"
            "- 开机自启动选项 (默认关闭)\n"
            "- 鼠标悬停显示 IP 地址（悬浮窗口）\n"
            "- 启动时窗口显示在鼠标附近\n"
            "- 新增软件图标和可自定义系统托盘图标\n"
            "\t命名规则必须为 clock.png\n"
            "创建日期：2025年3月25日\n"
            "最后更新日期：2025年3月29日\n"
            "\t感想：AI编程还是不太理想，费时还学不到东西，\n"
            "\t还得自己会，自己写才写的顺"
        )
        messagebox.showinfo("关于", about_text)

    # 更新日志
    def show_changelog(self):
        changelog_text = """
        V6.0---D250329\n
        - 更新了更新日志\n
        - 更新了关于说明\n
        - 优化了说明类文本的可读性和一致性\n
        - 优化了代码的可读性\n
        - 优化了线程问题\n
        
        -------------------------------------------\n
        V5.9---D250328\n
        - 修改了应用图标\n
        - 添加了对 clock.png 文件的识别，\n
        \t需要在同一目录下才可以被识别，\n
        \t如果有可用的 clock.png 图片，则将图片用于系统托盘处当作软件图标，\n
        \t若没有则显示为纯黄色背景图标\n
        false---可通过鼠标左击系统托盘图标来快速打开已隐藏的工具窗口，可以节省步骤\n
        \treason---系统级调用未能实现\n
        
        -------------------------------------------\n
        V5.8---D250328\n
        - 修改了代码逻辑\n
        \t将使用ico格式的代码模块替换为使用png格式的代码\n
        false---修改了系统任务栏的图标显示效果(更换了新的图标)\n
        \treason---需要手动配置 .png 文件\n
        
        ---------------------------------------------\n
        V5.7---D250328\n
        - 添加了可以隐藏所有窗口的功能\n
        - 添加了任务栏选项的功能，同时可以在后台保证软件不被系统阻塞\n
        - 修改了代码逻辑和显示效果\n
        
        -------------------------------------------\n
        V5.6---D250327\n
        - 修复了点击'立即休眠'后会改变'阻止系统休眠'的状态\n
        - ........(很多，很多........)\n
        
        ------------------------------------------\n 
        V5.0---D250326\n
        - 新功能：\n 
        - 添加了向指定 IP 地址持续发送 UDP 数据包的功能\n
        - 支持 MB/GB 单位和自定义发送频率\n 
        false---支持多个IP输入和同时发送\n
        \treason---发送数据逻辑较为复杂，以个人能力，暂时放弃\n
        - 实现了鼠标悬停在网速显示窗口时显示本机 IP 地址的功能\n 
        - 软件启动时，窗口会自动显示在鼠标附近\n 
        - 改进：\n 
        - 优化了网速显示的刷新间隔，用户可以自定义刷新间隔\n 
        - 改进了内存管理功能，提供更详细的内存使用信息\n 
        - 增强了软件的稳定性，减少了崩溃的可能性\n 
        - 修复的 bug：\n 
        - 修复了在某些情况下，软件无法阻止系统休眠的问题\n 
        - 修复了网速显示不准确的 bug\n 
        - 修复了内存管理功能中的一个内存泄漏问题\n 
        
        -----------------------------------------\n 
        V0.0->V4.9---D250325\n
        孩子太小了，不记得事情了......\n 
        """
        # 弹出窗口显示更新日志
        # 创建一个 Toplevel 窗口
        changelog_window = tk.Toplevel(self)
        changelog_window.title("更新日志")
        changelog_window.geometry("600x500")  # 设置窗口初始大小
        changelog_window.attributes('-topmost', True)  # 保持窗口置顶，与主程序风格一致
        changelog_window.config(bg="black")  # 设置背景色，与主程序风格一致
        # 创建 ScrolledText 控件，带滚动条
        text_area = scrolledtext.ScrolledText(
            changelog_window,
            wrap=tk.WORD,  # 自动换行
            width=50,  # 宽度
            height=15,  # 高度
            font=("Arial", 10),
            fg="white",  # 字体颜色
            bg="#333333",  # 背景颜色，与主程序风格一致
            insertbackground="white"  # 光标颜色（虽然这里是只读，但设置以防万一）
        )
        text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)  # 填充窗口并支持扩展
        # 插入更新日志文本
        text_area.insert(tk.INSERT, changelog_text)
        # 设置为只读，防止用户修改
        text_area.configure(state='disabled')
        # 绑定窗口关闭事件
        changelog_window.protocol("WM_DELETE_WINDOW", changelog_window.destroy)


    def update_time(self):
        """每秒更新主窗口时间显示"""
        time_str = datetime.now().strftime("%H:%M:%S")
        self.time_label.config(text=time_str)
        self.after(1000, self.update_time)

    def get_ip_address(self):
        """获取本机 IP 地址"""
        try:
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            return ip_address
        except Exception:
            return "无法获取 IP 地址"

    # -------------------- 数据包发送窗口及功能 --------------------
    def open_packet_sender_window(self):
        """打开数据包发送悬浮窗口"""
        if self.packet_sender_window:
            return

        self.packet_sender_window = tk.Toplevel(self)
        self.packet_sender_window.attributes('-topmost', True)
        self.packet_sender_window.config(bg="black")
        self.packet_sender_window.overrideredirect(True)

        # 定位数据包发送窗口在主窗口右侧
        clock_x = self.winfo_x()
        clock_y = self.winfo_y()
        clock_width = self.winfo_width()
        packet_width = 300
        packet_height = 180
        packet_x = clock_x + clock_width + 5
        packet_y = clock_y
        self.packet_sender_window.geometry(f"{packet_width}x{packet_height}+{packet_x}+{packet_y}")

        # 创建输入区域：目标 IP、数据包大小（及单位）、发送间隔
        ip_frame = tk.Frame(self.packet_sender_window, bg="black")
        ip_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(ip_frame, text="目标 IP 地址：", font=("Arial", 10), fg="white", bg="black").pack(side="left")
        self.ip_entry = tk.Entry(ip_frame, width=20, font=("Arial", 10), fg="white", bg="#333333",
                                 insertbackground="white")
        self.ip_entry.pack(side="left", padx=5)

        size_frame = tk.Frame(self.packet_sender_window, bg="black")
        size_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(size_frame, text="数据包大小：", font=("Arial", 10), fg="white", bg="black").pack(side="left")
        self.size_entry = tk.Entry(size_frame, width=10, font=("Arial", 10), fg="white", bg="#333333",
                                   insertbackground="white")
        self.size_entry.pack(side="left", padx=5)
        self.unit_var = tk.StringVar(value="MB")
        unit_menu = ttk.OptionMenu(size_frame, self.unit_var, "MB", "MB", "GB")
        unit_menu.pack(side="left", padx=5)
        unit_menu.config(width=5)

        freq_frame = tk.Frame(self.packet_sender_window, bg="black")
        freq_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(freq_frame, text="发送间隔（ms）：", font=("Arial", 10), fg="white", bg="black").pack(side="left")
        self.freq_entry = tk.Entry(freq_frame, width=10, font=("Arial", 10), fg="white", bg="#333333",
                                   insertbackground="white")
        self.freq_entry.pack(side="left", padx=5)
        self.freq_entry.insert(0, "1000")

        button_frame = tk.Frame(self.packet_sender_window, bg="black")
        button_frame.pack(fill="x", padx=10, pady=5)
        self.start_button = tk.Button(button_frame, text="开始", font=("Arial", 10), fg="white", bg="#555555",
                                      command=self.start_sending)
        self.start_button.pack(side="left", padx=5)
        self.pause_button = tk.Button(button_frame, text="暂停", font=("Arial", 10), fg="white", bg="#555555",
                                      command=self.pause_sending, state=tk.DISABLED)
        self.pause_button.pack(side="left", padx=5)

        self.packet_status_label = tk.Label(self.packet_sender_window,
                                            text="请输入参数并点击开始",
                                            font=("Arial", 10), fg="yellow", bg="black", pady=5)
        self.packet_status_label.pack(fill="x")

        # 绑定数据包发送窗口拖动事件
        self.packet_sender_window.bind("<Button-1>", self.start_move_packet)
        self.packet_sender_window.bind("<B1-Motion>", self.on_motion_packet)
        self.packet_sender_window.protocol("WM_DELETE_WINDOW", self.close_packet_sender_window)

    def close_packet_sender_window(self):
        """关闭数据包发送窗口"""
        if self.packet_sender_window:
            self.packet_sender_window.destroy()
            self.packet_sender_window = None

    def start_move_packet(self, event):
        """记录数据包发送窗口拖动起始位置"""
        self.packet_offset_x = event.x_root - self.packet_sender_window.winfo_x()
        self.packet_offset_y = event.y_root - self.packet_sender_window.winfo_y()

    def on_motion_packet(self, event):
        """根据记录的偏移量更新数据包发送窗口位置，实现窗口拖动"""
        new_x = event.x_root - self.packet_offset_x
        new_y = event.y_root - self.packet_offset_y
        self.packet_sender_window.geometry(f"+{new_x}+{new_y}")

    def start_sending(self):
        """开始发送数据包"""
        try:
            ip = self.ip_entry.get().strip()
            socket.inet_aton(ip)  # 验证 IP 合法性
            size = float(self.size_entry.get())
            if size <= 0:
                raise ValueError("包大小必须大于0")
            unit = self.unit_var.get()
            total_bytes = int(size * (1024 * 1024 if unit == "MB" else 1024 * 1024 * 1024))
            interval_ms = int(self.freq_entry.get())
            if interval_ms < 0:
                raise ValueError("发送间隔必须>=0")
        except Exception as e:
            self.packet_status_label.config(text=f"参数错误：{e}", fg="red")
            return

        self.is_sending = True
        self.bytes_sent = 0
        self.start_time = time.time()
        self.start_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.packet_status_label.config(text="开始发送数据包...", fg="green")

        send_thread = threading.Thread(target=self.send_packets_loop, args=(ip, total_bytes, interval_ms), daemon=True)
        send_thread.start()
        monitor_thread = threading.Thread(target=self.monitor_rate, daemon=True)
        monitor_thread.start()

    def pause_sending(self):
        """暂停发送数据包"""
        self.is_sending = False
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.packet_status_label.config(text="已暂停发送", fg="yellow")

    def send_packets_loop(self, ip, total_bytes, interval_ms):
        """持续发送数据包"""
        CHUNK_SIZE = 8192
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while self.is_sending:
            bytes_sent_in_loop = 0
            while bytes_sent_in_loop < total_bytes and self.is_sending:
                remaining = total_bytes - bytes_sent_in_loop
                send_size = CHUNK_SIZE if remaining >= CHUNK_SIZE else remaining
                try:
                    sock.sendto(b"X" * send_size, (ip, 12345))
                except Exception as e:
                    self.packet_status_label.config(text=f"发送失败：{e}", fg="red")
                    self.is_sending = False
                    break
                with self.lock:
                    self.bytes_sent += send_size
                bytes_sent_in_loop += send_size
            time.sleep(interval_ms / 1000.0)
        sock.close()

    def monitor_rate(self):
        """监控发送速率"""
        while True:
            time.sleep(1)
            if not self.is_sending:
                self.packet_status_label.config(text="已暂停发送", fg="yellow")
                break
            with self.lock:
                elapsed = time.time() - self.start_time
                rate = (self.bytes_sent * 8) / (1024 * 1024) / elapsed if elapsed > 0 else 0.0
            self.packet_status_label.config(text=f"发送中，速率：{rate:.2f} Mbps", fg="green")

    # -------------------- 网速显示窗口及设置 --------------------
    def open_network_window(self):
        """打开网速显示悬浮窗口"""
        if self.network_window:
            return

        self.network_window = tk.Toplevel(self)
        self.network_window.attributes('-topmost', True)
        self.network_window.config(bg="black")
        self.network_window.overrideredirect(True)

        clock_x = self.winfo_x()
        clock_y = self.winfo_y()
        clock_height = self.winfo_height()
        net_width = 230
        net_height = 35
        net_x = clock_x - int(net_width / 3.5)
        net_y = clock_y + clock_height + 8
        self.network_window.geometry(f"{net_width}x{net_height}+{net_x}+{net_y}")

        self.speed_label = tk.Label(self.network_window,
                                    text="⬆ 0 KB/s   ⬇ 0 KB/s",
                                    font=("Arial", 12), fg="white", bg="black")
        self.speed_label.pack(padx=10, pady=5)

        self.network_window.bind("<Button-1>", self.start_move_net)
        self.network_window.bind("<B1-Motion>", self.on_motion_net)
        self.network_window.bind("<Enter>", self.show_ip)
        self.network_window.bind("<Leave>", self.hide_ip)
        self.network_window.bind("<Button-3>", self.show_network_context_menu)
        self.network_window.protocol("WM_DELETE_WINDOW", self.close_network_window)

        self.old_stats = psutil.net_io_counters()
        self.update_network()

    def show_network_context_menu(self, event):
        """在网速窗口右键弹出菜单"""
        menu = tk.Menu(self.network_window, tearoff=0)
        menu.add_command(label="刷新间隔设置", command=self.open_refresh_settings_window)
        menu.post(event.x_root, event.y_root)

    def open_refresh_settings_window(self):
        """打开刷新间隔设置窗口"""
        if hasattr(self, 'refresh_settings_window') and self.refresh_settings_window is not None:
            return
        self.refresh_settings_window = tk.Toplevel(self.network_window)
        self.refresh_settings_window.overrideredirect(True)
        self.refresh_settings_window.attributes("-topmost", True)
        self.refresh_settings_window.config(bg="black")
        nx = self.network_window.winfo_x()
        ny = self.network_window.winfo_y()
        self.refresh_settings_window.geometry(f"250x100+{nx + 50}+{ny + 50}")

        self.refresh_settings_window.bind("<Button-1>", self.start_drag_refresh)
        self.refresh_settings_window.bind("<B1-Motion>", self.do_drag_refresh)

        label = tk.Label(self.refresh_settings_window,
                         text="刷新间隔（毫秒）",
                         font=("Arial", 10), fg="white", bg="black")
        label.pack(pady=5)
        self.refresh_entry = tk.Entry(self.refresh_settings_window,
                                      font=("Arial", 10), fg="white", bg="#333333", insertbackground="white")
        self.refresh_entry.insert(0, str(self.network_refresh_interval))
        self.refresh_entry.pack(pady=5)
        ok_button = tk.Button(self.refresh_settings_window,
                              text="确定", font=("Arial", 10), fg="white", bg="#555555",
                              command=self.set_new_refresh_interval)
        ok_button.pack(pady=5)

    def start_drag_refresh(self, event):
        """记录刷新设置窗口拖动起始位置"""
        self.refresh_drag_x = event.x
        self.refresh_drag_y = event.y

    def do_drag_refresh(self, event):
        """拖动刷新设置窗口"""
        x = self.refresh_settings_window.winfo_x() + (event.x - self.refresh_drag_x)
        y = self.refresh_settings_window.winfo_y() + (event.y - self.refresh_drag_y)
        self.refresh_settings_window.geometry(f"+{x}+{y}")

    def set_new_refresh_interval(self):
        """设置新的刷新间隔"""
        try:
            new_interval = int(self.refresh_entry.get())
            if new_interval < 1:
                raise ValueError
            self.network_refresh_interval = new_interval
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数（>=1）")
            return
        self.refresh_settings_window.destroy()
        self.refresh_settings_window = None

    def show_ip(self, event):
        """延迟显示 IP 地址窗口"""
        if hasattr(self, 'show_ip_after_id'):
            self.network_window.after_cancel(self.show_ip_after_id)
        self.is_hovering = True
        self.show_ip_after_id = self.network_window.after(300, self._display_ip)

    def _display_ip(self):
        """显示 IP 地址窗口"""
        if not self.is_hovering:
            return
        if self.ip_window:
            return

        self.ip_window = tk.Toplevel(self)
        self.ip_window.attributes('-topmost', True)
        self.ip_window.config(bg="black")
        self.ip_window.overrideredirect(True)

        net_x = self.network_window.winfo_x()
        net_y = self.network_window.winfo_y()
        net_width = self.network_window.winfo_width()
        net_height = self.network_window.winfo_height()
        ip_width = 180
        ip_height = 30
        ip_x = net_x
        ip_y = net_y + net_height + 5
        self.ip_window.geometry(f"{ip_width}x{ip_height}+{ip_x}+{ip_y}")

        ip_address = self.get_ip_address()
        ip_label = tk.Label(self.ip_window,
                            text=f"IPv4 地址: {ip_address}",
                            font=("Arial", 10), fg="white", bg="black",
                            anchor="w", padx=5, pady=5)
        ip_label.pack(fill="x")

    def hide_ip(self, event):
        """隐藏 IP 地址窗口"""
        self.is_hovering = False
        if hasattr(self, 'show_ip_after_id'):
            self.network_window.after_cancel(self.show_ip_after_id)
        if self.ip_window:
            self.ip_window.destroy()
            self.ip_window = None

    def close_network_window(self):
        """关闭网速显示窗口"""
        if self.network_window:
            self.hide_ip(None)
            self.network_window.destroy()
            self.network_window = None

    def update_network(self):
        """更新网速显示"""
        if self.network_window:
            new_stats = psutil.net_io_counters()
            upload_speed = (new_stats.bytes_sent - self.old_stats.bytes_sent) / 1024
            download_speed = (new_stats.bytes_recv - self.old_stats.bytes_recv) / 1024
            self.old_stats = new_stats

            if upload_speed >= 1024:
                upload_speed /= 1024
                upload_unit = "MB/s"
            else:
                upload_unit = "KB/s"

            if download_speed >= 1024:
                download_speed /= 1024
                download_unit = "MB/s"
            else:
                download_unit = "KB/s"

            self.speed_label.config(text=f"⬆ {upload_speed:.2f} {upload_unit}   ⬇ {download_speed:.2f} {download_unit}")
            self.network_window.after(self.network_refresh_interval, self.update_network)

    def start_move_net(self, event):
        """记录网速窗口拖动起始位置"""
        self.net_x = event.x_root - self.network_window.winfo_x()
        self.net_y = event.y_root - self.network_window.winfo_y()

    def on_motion_net(self, event):
        """拖动网速窗口"""
        x = event.x_root - self.net_x
        y = event.y_root - self.net_y
        self.network_window.geometry(f"+{x}+{y}")

    # -------------------- 内存管理窗口 --------------------
    def open_memory_window(self):
        """打开内存管理窗口"""
        if self.memory_window:
            return

        self.memory_window = tk.Toplevel(self)
        self.memory_window.attributes('-topmost', True)
        self.memory_window.config(bg="black")
        self.memory_window.overrideredirect(True)

        clock_x = self.winfo_x()
        clock_y = self.winfo_y()
        mem_width = 300
        mem_height = 150
        mem_x = clock_x - int(mem_width / 3)
        mem_y = clock_y - mem_height - 5
        self.memory_window.geometry(f"{mem_width}x{mem_height}+{mem_x}+{mem_y}")

        self.mem_usage_label = tk.Label(self.memory_window,
                                        text=self.memory_manager.get_memory_usage(),
                                        font=("Arial", 12), fg="white", bg="black",
                                        justify="left", anchor="w", padx=10, pady=5)
        self.mem_usage_label.pack(fill="x")

        input_frame = tk.Frame(self.memory_window, bg="black")
        input_frame.pack(fill="x", padx=10)
        tk.Label(input_frame, text="内存大小（MB）：", font=("Arial", 10), fg="white", bg="black").pack(side="left")
        self.mem_size_entry = tk.Entry(input_frame, width=10, font=("Arial", 10), fg="white", bg="#333333",
                                       insertbackground="white")
        self.mem_size_entry.pack(side="left", padx=5)

        button_frame = tk.Frame(self.memory_window, bg="black")
        button_frame.pack(fill="x", padx=10, pady=5)
        tk.Button(button_frame, text="增加内存", font=("Arial", 10), fg="white", bg="#555555",
                  command=self.add_memory).pack(side="left", padx=5)
        tk.Button(button_frame, text="减少内存", font=("Arial", 10), fg="white", bg="#555555",
                  command=self.reduce_memory).pack(side="left", padx=5)
        tk.Button(button_frame, text="重置内存", font=("Arial", 10), fg="white", bg="#555555",
                  command=self.reset_memory).pack(side="left", padx=5)

        self.mem_status_label = tk.Label(self.memory_window,
                                         text="欢迎使用内存管理器！",
                                         font=("Arial", 10), fg="yellow", bg="black", pady=5)
        self.mem_status_label.pack(fill="x")

        self.memory_window.bind("<Button-1>", self.start_move_mem)
        self.memory_window.bind("<B1-Motion>", self.on_motion_mem)
        self.memory_window.protocol("WM_DELETE_WINDOW", self.close_memory_window)

    def close_memory_window(self):
        """关闭内存管理窗口"""
        if self.memory_window:
            self.memory_window.destroy()
            self.memory_window = None

    def start_move_mem(self, event):
        """记录内存管理窗口拖动起始位置"""
        self.mem_x = event.x_root - self.memory_window.winfo_x()
        self.mem_y = event.y_root - self.memory_window.winfo_y()

    def on_motion_mem(self, event):
        """拖动内存管理窗口"""
        x = event.x_root - self.mem_x
        y = event.y_root - self.mem_y
        self.memory_window.geometry(f"+{x}+{y}")

    def update_mem_usage(self):
        """更新内存占用显示"""
        if self.memory_window:
            self.mem_usage_label.config(text=self.memory_manager.get_memory_usage())

    def add_memory(self):
        """处理增加内存操作"""
        try:
            size_mb = int(self.mem_size_entry.get())
            if size_mb <= 0:
                messagebox.showerror("错误", "请输入正整数！")
                return
            message = self.memory_manager.add_memory(size_mb)
            self.mem_status_label.config(text=message, fg="orange")
            self.update_mem_usage()
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字！")

    def reduce_memory(self):
        """处理减少内存操作"""
        try:
            size_mb = int(self.mem_size_entry.get())
            if size_mb <= 0:
                messagebox.showerror("错误", "请输入正整数！")
                return
            message = self.memory_manager.reduce_memory(size_mb)
            self.mem_status_label.config(text=message, fg="orange" if "成功" in message else "red")
            self.update_mem_usage()
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字！")

    def reset_memory(self):
        """处理重置内存操作"""
        message = self.memory_manager.reset_memory()
        self.mem_status_label.config(text=message, fg="orange")
        self.update_mem_usage()


    # -------------------- 程序退出 --------------------
    def on_closing(self):
        """退出程序时关闭所有窗口"""
        self.restore_sleep()
        if self.network_window:
            self.network_window.destroy()
        if self.memory_window:
            self.memory_window.destroy()
        if self.ip_window:
            self.ip_window.destroy()
        if self.packet_sender_window:
            self.close_packet_sender_window()
        self.memory_manager.reset_memory()
        self.destroy()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("此程序仅支持 Windows！")
        sys.exit(1)
    ClockWindow()

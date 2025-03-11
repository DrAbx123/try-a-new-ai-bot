import sys
import traceback

try:
    print("正在启动Claude Sonnet AI聊天界面...")
    from frontend_sonnet import main
    print("成功导入main函数")
    
    if __name__ == "__main__":
        try:
            print("开始执行main函数...")
            main()
            print("main函数执行完成")
        except Exception as e:
            print(f"运行main函数时出错: {str(e)}")
            traceback.print_exc()
except Exception as e:
    print(f"导入模块时出错: {str(e)}")
    traceback.print_exc()

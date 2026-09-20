"""旧生成数据任务已停用。历史库保留用于审计，不再进入产品。"""
def complete_all_shareholders():
    raise RuntimeError("旧生成数据流程已停用；请使用 dsh_stock_cli.py holders --refresh 或真实披露适配器")
if __name__ == '__main__':
    complete_all_shareholders()

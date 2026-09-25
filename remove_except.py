with open(r'C:\Users\Lyang\Desktop\Python\anti-securities\Anti Securities Report.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

while lines and ('AI 调用失败' in lines[-1] or 'except Exception as e:' in lines[-1] or lines[-1].strip() == '' or 'status_box.update' in lines[-1]):
    lines.pop()

with open(r'C:\Users\Lyang\Desktop\Python\anti-securities\Anti Securities Report.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

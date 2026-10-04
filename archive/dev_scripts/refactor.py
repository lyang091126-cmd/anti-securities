with open(r'C:\Users\Lyang\Desktop\Python\anti-securities\Anti Securities Report_backup.py', 'r', encoding='utf-8') as f:
    content = f.read()

except_block = '        except Exception as e:\n            st.error(f"⚠️ 生成报告时发生错误 (API 调用失败或格式解析错误): {e}")\n'
content = content.replace(except_block, '')

ui_marker = '            # ===== 提前获取股票 Profile（真实机构持仓数据，无编造） =====\n'
parts = content.split(ui_marker)

if len(parts) == 2:
    top = parts[0]
    ui_part = ui_marker + parts[1]
    
    new_top = top + except_block
    
    unindented_ui_lines = []
    for l in ui_part.split('\n'):
        if l.startswith('            '):
            unindented_ui_lines.append(l[8:])
        elif l.startswith('        '):
            unindented_ui_lines.append(l[8:] if len(l.strip())>0 else '')
        elif l.startswith('    '):
            unindented_ui_lines.append(l[4:] if len(l.strip())>0 else '')
        else:
            unindented_ui_lines.append(l)
    
    new_ui_part = '\n'.join(unindented_ui_lines)
    
    top_parts = new_top.split('if generate_btn:\n')
    if len(top_parts) == 2:
        header = top_parts[0]
        llm_body = top_parts[1]
        
        new_llm_body = '    if generate_btn:\n'
        for l in llm_body.split('\n'):
            if len(l) > 0:
                new_llm_body += '    ' + l + '\n'
            else:
                new_llm_body += '\n'
                
        new_outer = 'if ticker_input and all_data and all_data.get(\'hist_1y\') is not None:\n'
        
        final_content = header + new_outer + new_llm_body + new_ui_part
        
        with open(r'C:\Users\Lyang\Desktop\Python\anti-securities\Anti Securities Report.py', 'w', encoding='utf-8') as f:
            f.write(final_content)
        print('Refactor complete.')
    else:
        print('if generate_btn not found')
else:
    print('ui_marker not found')

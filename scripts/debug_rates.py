import openpyxl
wb = openpyxl.load_workbook('docs/作业验收用例_本组填写.xlsx', data_only=True)
ws = wb['测试说明']
rows = list(ws.iter_rows(values_only=True))
for idx, r in enumerate(rows,1):
    print(idx, r)
print('\n--- scanning after 计费费率 ---')
for idx, r in enumerate(rows):
    if r and r[0] == '计费费率':
        for j, s in enumerate(rows[idx+1:idx+10], idx+2):
            print(j, repr(s[1]) if s and len(s)>1 else None, type(s[1]) if s and len(s)>1 else None, '->', repr(s[2]) if s and len(s)>2 else None, type(s[2]) if s and len(s)>2 else None)
        break

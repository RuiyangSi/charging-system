import openpyxl

path = '副本作业验收用例_filled.xlsx'
wb = openpyxl.load_workbook(path, data_only=True)
ws = wb['测试用例']

for r in range(1, 31):
    vals = [ws.cell(row=r, column=c).value for c in range(1, 21)]
    print(r, vals)

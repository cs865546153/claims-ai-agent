s = "  Hello ,da "
s = s.strip().lower()
parts = s.split(",")              # 返回 list
print(parts)

# joined = "-".join(items)          # 注意是 str.join(iterable)
# msg = f"用户 {name} 金额 {amount}"  # f-string，最常用
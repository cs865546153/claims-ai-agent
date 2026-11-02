# 语法手册：Row 与表达式

适用版本：RowFlow 演示规范 1.0。本文定义记录模型、字段读取、空值及转换行为。

## 1. Row 是什么

`Row` 是单条记录的只读包装，底层为按插入顺序保存字段的 `Map<String,Object>`。流在操作符之间始终传递 Row；从源获得的 Map，以及 `map` 等操作符返回的 Map，都会由框架包装。

字段名区分大小写。`userId` 和 `userid` 是两个字段。字段允许嵌套 Map/List，值限于字符串、数字、布尔值、`null` 和上述容器；不接受自定义对象、闭包或流作为字段值。

## 2. 读取与构造

| 写法 | 返回值 | 说明 |
| --- | --- | --- |
| `r['name']` | 字段值 | 缺失字段返回 `null` |
| `r.get('name')` | 字段值 | 与方括号相同 |
| `r.has('name')` | Boolean | 区分缺失字段与值为 `null` 的已存在字段 |
| `r.toMap()` | Map | 递归复制后的普通 Map/List，不会暴露底层容器 |
| `row([name: 'Alice'])` | Row | 显式构造 Row |
| `r.withFields([active: true])` | 新 Row | 保留原字段并覆盖合并给定字段 |

`r.withFields(Map)` 是 Row 方法；`stream.withFields { r -> Map }` 是流操作符，两者分别作用于一行和每一行。

统一使用方括号读取字段，不使用 `r.name` 风格，以免与 Row 方法名冲突。`r['profile.city']` 读取的是字面字段名 `profile.city`，不会访问嵌套对象。

嵌套读取片段：

```groovy
def city = r['profile']?.get('city')
```

这里假设 `profile` 为 Map 或 `null`；若其实际为字符串等类型，应先修正源契约或在上游规范字段。

## 3. 只读与覆盖

Row 及其内部 Map/List 递归只读。框架在输入和操作符输出边界复制容器，防止多行共享可变对象。转换闭包返回新 Map/Row，不直接赋值修改输入。

```groovy
// map：输出只有这里列出的两个字段
.map { r -> [orderId: r['orderId'], amount: decimal(r['amount'])] }

// withFields：保留原字段，并覆盖 amount、增加 highValue
.withFields { r ->
    def amount = decimal(r['amount'])
    [amount: amount, highValue: amount >= 100.00G]
}
```

上面是链式片段。以下写法不受支持，会触发只读错误：`r['amount'] = 100`、`r['items'].add(...)`。不需要通过修改原 Row 来“把值传到下一步”。

覆盖只发生在顶层：原字段 `profile: [city: '杭州', level: 'VIP']` 与新字段 `profile: [city: '上海']` 合并后，`profile` 整体替换，`level` 不再保留。

## 4. 空值、缺失和默认值

```groovy
.map { r ->
    [
        userId: r['userId'],
        city: r['city'] == null ? '未知' : r['city'],
        amount: r['amount'] == null ? 0.00G : decimal(r['amount'])
    ]
}
```

字段缺失与显式 `null` 在普通读取时相同；需要区分时使用 `has`。输出 Map 中显式出现的 `null` 字段会保留，序列化时不会自动删除。

Groovy 的 `?:` 会把 `0`、`false`、空字符串也视为假值。仅在希望这些值也走默认值时使用它；只想处理空值时使用 `== null ? 默认值 : 原值`。

`filter` 必须返回真正的 Boolean。框架不自动把数字、字符串或 Row 转换为布尔值。

## 5. 数值与金额

`decimal(value)` 接受 Number，或去掉首尾空白后符合 `[+-]?\d+(\.\d+)?` 的十进制字符串；不接受 `null`、空字符串、千分位、货币符号、指数形式、NaN 或无穷大。非法值报 `RF-TYPE-001`。

```groovy
def threshold = decimal(param('minAmount', '100.00'))

def result = from('orders')
    .filter { r -> r['amount'] != null }
    .withFields { r -> [amount: decimal(r['amount'])] }
    .filter { r -> r['amount'] >= threshold }
```

`G` 后缀可用于 Groovy 的 BigDecimal 小数字面量，例如 `120.50G`。金额推荐使用 BigDecimal；`decimal` 对合法输入执行十进制转换，不额外舍入，业务舍入需先补充明确规则。1.0 没有 `roundMoney` 之类的内置函数。

JSON 中数值的小数显示位数不作为验收条件；`100.0` 和 `100.00` 按数值等价处理。字符串 `'100.00'` 则仍然是字符串。

## 6. 常用表达式白名单

| 类别 | 支持写法 |
| --- | --- |
| 比较与逻辑 | `==`、`!=`、`>`、`>=`、`<`、`<=`、`&&`、`||`、`!` |
| 算术 | `+`、`-`、`*`、`/`、`%`，使用前处理空值与类型 |
| 条件 | `条件 ? A : B`、`?:`、`if/else` |
| 字符串 | `toString()`、`trim()`、`toUpperCase()`、`toLowerCase()`、`startsWith()`、`endsWith()`、`contains()` |
| Map | `get()`、`containsKey()`、`size()`、方括号读取 |
| List | `size()`、`isEmpty()`、`contains()`、方括号读取、局部 List 的 `collect { item -> ... }` |
| 安全导航 | `value?.method()` |
| 构造 | Map/List 字面量、局部 `def`、`row(Map)`、`decimal(value)` |

`items.collect { item -> [...] }` 仅用于把当前行内的 List 转成新 List，常用于 `flatMap`。它不是 RowStream 的终结方法；RowStream 不支持 `collect`。

字符串标识符统一采用源契约给定的类型。比如用户 ID 为 String 时，`'U001'` 与 `'U001'` 相等；不要通过大小写转换或截断改变 ID，除非需求明确要求。

## 7. 关联、去重与分组的键

`distinct`、`join`、`groupBy` 的键支持 String、Boolean、有限 Number、`null`，以及由这些标量组成的 List；不支持 Map、Row 或嵌套 List。

- String 按内容比较，区分大小写；字符串和数值不自动互转。
- Number 按数学值比较，`1`、`1L`、`1.0G` 视为同键。
- List 按位置逐项比较，可以作为联合键，例如 `[r['tenantId'], r['userId']]`。
- `distinct` 把相同空键视为重复；`groupBy` 把相同空键归入同组。
- `join` 中键为 `null` 或联合键任一分量为 `null` 时不匹配，包括两边同时为空的情况。

这些是框架定义的键语义，不能直接用某个语言容器的默认哈希行为替代。

## 8. 时间字段

1.0 将时间作为字符串透传，不提供日期解析、时区转换或窗口统计 API。服务契约中的 `createdAt` 使用 UTC ISO 8601，例如 `2026-10-18T08:00:00Z`。只有格式、时区和精度一致的时间字符串，才能依赖字典序排序或比较；复杂日期需求应先扩展规范。

/* @rowflow-demo
{
  "version": "1.0",
  "title": "多仓库存预警与补货汇总",
  "description": "筛选库存不足的 SKU，关联商品单价，计算各仓库的补货数量与预算。",
  "parameters": {"tenantId": "T001", "minBudget": "0"},
  "mocks": {
    "inventory": {
      "response": {
        "data": {
          "items": [
            {"warehouse": "杭州仓", "sku": "P001", "stock": 3, "safetyStock": 10},
            {"warehouse": "杭州仓", "sku": "P002", "stock": 20, "safetyStock": 10},
            {"warehouse": "上海仓", "sku": "P001", "stock": 8, "safetyStock": 12},
            {"warehouse": "上海仓", "sku": "P003", "stock": 2, "safetyStock": 5},
            {"warehouse": "杭州仓", "sku": "P004", "stock": 1, "safetyStock": 4},
            {"warehouse": "成都仓", "sku": "P002", "stock": 15, "safetyStock": 10},
            {"warehouse": "成都仓", "sku": "P004", "stock": 0, "safetyStock": 0}
          ]
        }
      }
    },
    "products": {
      "response": {
        "data": {
          "products": [
            {"sku": "P001", "productName": "机械键盘", "unitPrice": "129.90"},
            {"sku": "P002", "productName": "无线鼠标", "unitPrice": "59.50"},
            {"sku": "P003", "productName": "显示器", "unitPrice": "899.00"},
            {"sku": "P004", "productName": "扩展坞", "unitPrice": "199.00"}
          ]
        }
      }
    }
  }
}
*/
pipeline(name: 'inventory_replenishment', dslVersion: '1.0') {
    def minBudget = decimal(param('minBudget', '0'))

    source('inventory', [
        type: 'http',
        method: 'GET',
        url: 'https://demo.rowflow.example/api/inventory',
        query: [tenantId: param('tenantId', 'T001')],
        credentialRef: 'demo-inventory-reader',
        rowsPath: 'data.items'
    ])
    source('products', [
        type: 'rpc',
        registryRef: 'demo-product-rpc',
        service: 'demo.catalog.ProductService',
        method: 'listProducts',
        serviceVersion: '1.0',
        args: [tenantId: param('tenantId', 'T001')],
        rowsPath: 'data.products'
    ])

    // @step inventory 库存记录
    def inventory = from('inventory')

    // @step products 商品资料
    def products = from('products')

    // @step low_stock 筛选库存不足的 SKU
    def lowStock = inventory.filter { r -> r['stock'] < r['safetyStock'] }

    // @step enrich 关联商品单价
    def enriched = lowStock.join(products, [
        type: 'inner',
        leftKey: { l -> l['sku'] },
        rightKey: { r -> r['sku'] }
    ]) { inventoryRow, product ->
        [
            warehouse: inventoryRow['warehouse'],
            sku: inventoryRow['sku'],
            stock: inventoryRow['stock'],
            safetyStock: inventoryRow['safetyStock'],
            unitPrice: decimal(product['unitPrice'])
        ]
    }

    // @step budget 计算补货量和预算
    def budgeted = enriched.withFields { r ->
        def qty = r['safetyStock'] - r['stock']
        [replenishQty: qty, estimatedCost: qty * r['unitPrice']]
    }

    // @step warehouse_groups 按仓库分组
    def groups = budgeted.groupBy([warehouse: { r -> r['warehouse'] }])

    // @step summary 汇总各仓库补货
    def summary = groups.aggregate([
        skuCount: count(),
        replenishQty: sum { r -> r['replenishQty'] },
        estimatedCost: sum { r -> r['estimatedCost'] }
    ])

    // @step threshold 按最低预算筛选
    def qualified = summary.filter { r -> r['estimatedCost'] >= minBudget }

    // @step rank 按预算降序排列
    def result = qualified.sorted([direction: 'desc']) { r -> r['estimatedCost'] }

    // @step output 输出补货建议
    emit(result)
}

func score(_ values: [Int]) -> Int {
    var total = 0

    for value in values {
        if value > 0 {
            total = total + value
        } else {
            continue
        }
    }

    while total > 100 {
        total = total - 10
    }

    repeat {
        total = total - 1
    } while total > 50

    guard total >= 0 else {
        return 0
    }

    switch total {
    case 0:
        return 0
    case 1:
        return 1
    default:
        return total
    }
}

struct MathBox {
    func normalize(_ input: Int) -> Int {
        if input < 0 {
            return 0
        }

        return input
    }
}


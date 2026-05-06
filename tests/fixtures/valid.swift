import Foundation

struct User {
    let id: Int
    var name: String

    func rename(to newName: String) {
    }
}

extension User {
    func greeting() -> String {
        "Hello"
    }
}

func makeUser() -> User {
    User(id: 1, name: "Ana")
}


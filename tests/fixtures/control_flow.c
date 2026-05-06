#include <stddef.h>

int score(const int *values, size_t count)
{
    int total = 0;

    for (size_t i = 0; i < count; i++) {
        if (values[i] > 0) {
            total += values[i];
        } else {
            continue;
        }
    }

    while (total > 100) {
        total -= 10;
    }

    do {
        total -= 1;
    } while (total > 50);

    if (total < 0) {
        return 0;
    }

    switch (total) {
    case 0:
        return 0;
    case 1:
        return 1;
    default:
        return total;
    }
}

int mathbox_normalize(int input)
{
    if (input < 0) {
        return 0;
    }

    return input;
}

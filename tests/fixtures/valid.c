#include <stddef.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    int id;
    char *name;
} User;

void user_rename(User *user, const char *new_name)
{
    free(user->name);
    user->name = strdup(new_name);
}

const char *user_greeting(const User *user)
{
    (void)user;
    return "Hello";
}

User make_user(int id, const char *name)
{
    User u;
    u.id = id;
    u.name = strdup(name);
    return u;
}

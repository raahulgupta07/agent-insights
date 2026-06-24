<template>
  <div class="bg-gray-50">
    <UNotifications />
    <slot />
  </div>
</template>

<script setup lang="ts">
const { signIn, signOut, token, data: currentUser, status, lastRefreshedAt, getSession } = useAuth()
const route = useRoute()

// (Intercom support-chat launcher removed entirely — vendor bubble + script.)

onMounted(async () => {
  // If redirected with an access_token in query, let the target page set the token first
  if (route.query.access_token) {
    return
  }
  await getSession({ force: true })
})

</script>
<template>
  <!-- Contextual left rail: shows ONLY the active top-nav group's items.
       Hidden on pages with no group (Home, Agent Studios, detail pages that
       own their own rail). One group at a time — never all groups stacked. -->
  <aside
    v-if="activeGroup"
    class="cag-rail shrink-0 h-full overflow-y-auto"
  >
    <div class="px-2.5 pt-5 pb-3">
      <div class="cag-rail-eyebrow">{{ $t(activeGroup.title) }}</div>
    </div>

    <nav class="px-2.5 pb-4 space-y-0.5">
      <template v-for="item in activeGroup.items" :key="item.key">
        <!-- Action item (e.g. MCP Server modal) -->
        <button
          v-if="item.action"
          @click="item.action && item.action()"
          class="cag-rail-link"
        >
          <span class="cag-rail-ic">
            <UIcon v-if="item.icon" :name="item.icon" />
            <component v-else-if="item.component" :is="item.component" class="w-[17px] h-[17px]" />
          </span>
          <span class="flex-1 text-start truncate">{{ $t(item.label) }}</span>
        </button>

        <!-- Route item -->
        <NuxtLink
          v-else
          :to="item.href"
          class="cag-rail-link"
          :class="isRouteActive(item.activePath || item.href!) ? 'cag-rail-active' : ''"
        >
          <span class="cag-rail-ic">
            <UIcon v-if="item.icon" :name="item.icon" />
            <component v-else-if="item.component" :is="item.component" class="w-[17px] h-[17px]" />
          </span>
          <span class="flex-1 truncate">{{ $t(item.label) }}</span>
        </NuxtLink>
      </template>
    </nav>
  </aside>
</template>

<script setup lang="ts">
  const { activeGroup, isRouteActive } = useAppNav()
</script>

<style scoped>
.cag-rail {
  width: 224px;
  background: #F2EBE0;
  border-right: 1px solid #E9E0D3;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.cag-rail-eyebrow {
  font-size: 10.5px;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: #9a958c;
  font-weight: 700;
}
.cag-rail-link {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  padding: 9px 11px;
  border-radius: 11px;
  font-size: 13.5px;
  font-weight: 500;
  color: #574E44;
  text-decoration: none;
  transition: background .12s, color .12s;
}
.cag-rail-link:hover {
  background: rgba(0, 0, 0, .04);
  color: #1A1611;
}
.cag-rail-ic {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  flex: 0 0 17px;
  color: #8c8479;
}
.cag-rail-active {
  background: #fff;
  color: #A8330F;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .05);
}
.cag-rail-active .cag-rail-ic {
  color: #C2541E;
}
</style>

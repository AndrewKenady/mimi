<script lang="ts">
	import { page } from '$app/state';
	import ChatView from '$components/ChatView.svelte';
</script>

<svelte:head><title>Chat · MIMI</title></svelte:head>
<ChatView id={page.params.id ?? null} />

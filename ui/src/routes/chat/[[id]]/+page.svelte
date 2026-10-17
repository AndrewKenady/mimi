<script lang="ts">
	import { page } from '$app/state';
	import ChatView from '$components/ChatView.svelte';
	import { t } from '$lib/i18n/index.svelte';
</script>

<svelte:head><title>{t('chat.pageTitle')}</title></svelte:head>
<ChatView id={page.params.id ?? null} />

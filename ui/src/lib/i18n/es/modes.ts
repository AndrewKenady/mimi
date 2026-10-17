// Core's chat modes by id: [name, description]. Shared by the chat and Settings areas so a mode
// has one name everywhere. Unknown ids (custom modes) keep Core's own wording.
export const MODES: Record<string, [string, string]> = {
	everyday: ['Día a día', 'Ayuda general, con fuentes cuando importa.'],
	road_trip: ['De viaje', 'Lugares, historia y relatos a lo largo del camino.'],
	field_medic: ['Socorrista', 'Primeros auxilios y salud, con base en WikiMed.'],
	fix_it: ['Arreglos', 'Reparaciones, bricolaje y solución de problemas.'],
	study: ['Estudio', 'Aprende lo que quieras: artículos, charlas y libros.'],
	storyteller: ['Cuentacuentos', 'Cuentos, poemas y libros clásicos.']
};

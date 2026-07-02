import { http, HttpResponse } from 'msw';
import { environment } from '../../environments/environment';
import {
  moodleCoursesData,
  moodleCourseStructure,
} from '../fixtures/moodle.fixture';

const api = environment.apiBaseUrl;
const base = `${api}/chatbots`;

export const moodleHandlers = [
  http.get(`${base}/:id/moodle-courses`, ({ params }) => {
    return HttpResponse.json(moodleCoursesData(params['id'] as string));
  }),

  http.patch(`${base}/:id/moodle-courses`, async ({ params, request }) => {
    const body = (await request.json()) as { course_ids: string[] };
    return HttpResponse.json({
      message: 'Courses updated',
      chatbot_id: params['id'],
      courses_added: body.course_ids ?? [],
      courses_removed: [],
      total_added: body.course_ids?.length ?? 0,
      total_removed: 0,
      current_courses: body.course_ids ?? [],
      total_courses: body.course_ids?.length ?? 0,
      reindexing: true,
    });
  }),

  http.get(`${base}/:id/moodle-courses/:courseId/structure`, ({ params }) => {
    return HttpResponse.json(moodleCourseStructure(params['courseId'] as string));
  }),

  http.get(`${base}/:id/moodle-content/:courseId/parsed`, ({ params, request }) => {
    const url = new URL(request.url);
    const activityId = url.searchParams.get('activity_id');
    const fileId = url.searchParams.get('file_id');
    const sectionId = url.searchParams.get('section_id');
    const entryId = url.searchParams.get('entry_id');
    const label = fileId ?? entryId ?? activityId ?? sectionId ?? (params['courseId'] as string);
    return HttpResponse.json({
      file_name: `moodle-${label}.pdf`,
      total_chunks: 2,
      content: `# Contenu Moodle ${label}\n\nContenu de démonstration provenant de Moodle.\n\n- Section: ${sectionId ?? '—'}\n- Activité: ${activityId ?? '—'}\n- Fichier: ${fileId ?? '—'}\n- Entrée de glossaire: ${entryId ?? '—'}\n`,
    });
  }),
];

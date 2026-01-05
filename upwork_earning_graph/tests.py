from django.test import TestCase, Client
from django.urls import reverse, resolve
from upwork_earning_graph.views import home, about, contact


class MainViewsTestCase(TestCase):

    def setUp(self):
        self.client = Client()

    def test_home_view_status_code(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_home_view_uses_correct_template(self):
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'index.html')

    def test_home_view_context(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['page_title'], 'Home')

    def test_about_view_status_code(self):
        response = self.client.get(reverse('about'))
        self.assertEqual(response.status_code, 200)

    def test_about_view_uses_correct_template(self):
        response = self.client.get(reverse('about'))
        self.assertTemplateUsed(response, 'about.html')

    def test_about_view_context(self):
        response = self.client.get(reverse('about'))
        self.assertEqual(response.context['page_title'], 'About')

    def test_contact_view_status_code(self):
        response = self.client.get(reverse('contact'))
        self.assertEqual(response.status_code, 200)

    def test_contact_view_uses_correct_template(self):
        response = self.client.get(reverse('contact'))
        self.assertTemplateUsed(response, 'contact.html')

    def test_contact_view_context(self):
        response = self.client.get(reverse('contact'))
        self.assertEqual(response.context['page_title'], 'Contact')


class URLRoutingTestCase(TestCase):

    def test_home_url_resolves(self):
        url = reverse('home')
        self.assertEqual(resolve(url).func, home)

    def test_about_url_resolves(self):
        url = reverse('about')
        self.assertEqual(resolve(url).func, about)

    def test_contact_url_resolves(self):
        url = reverse('contact')
        self.assertEqual(resolve(url).func, contact)

    def test_home_url_path(self):
        url = reverse('home')
        self.assertEqual(url, '/')

    def test_about_url_path(self):
        url = reverse('about')
        self.assertEqual(url, '/about/')

    def test_contact_url_path(self):
        url = reverse('contact')
        self.assertEqual(url, '/contact/')
